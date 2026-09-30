from __future__ import annotations

import asyncio
import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from oc8 import models as m
from oc8.oauth import http as oauth_http
from oc8.oauth.client import ResolvedClient
from oc8.oauth.errors import OAuthExchangeFailed, OAuthReauthRequired
from oc8.oauth.openai_chatgpt_params import TOKEN_URL as CHATGPT_TOKEN_URL
from oc8.oauth.tokens import (
    EXPIRY_SKEW_SECONDS,
    access_ref,
    exchange_code,
    extract_chatgpt_account_id,
    get_access_token,
    refresh_ref,
)
from oc8.oauth.xai_grok_params import TOKEN_URL as GROK_TOKEN_URL
from oc8.secrets.service import resolve_secret, store_secret
from tests.conftest import AppSessionFactory

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _kek(monkeypatch: pytest.MonkeyPatch) -> None:
    from oc8 import config

    monkeypatch.setattr(
        config.get_settings(),
        "secret_kek",
        base64.b64encode(bytes(range(32))).decode(),
        raising=False,
    )
    monkeypatch.setattr(config.get_settings(), "google_oauth_client_id", "plat-id", raising=False)
    monkeypatch.setattr(
        config.get_settings(), "google_oauth_client_secret", "plat-sec", raising=False
    )


class _Recorder:
    """Counts token-endpoint hits and serves a scripted response."""

    def __init__(self, body: dict[str, object], status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code
        self.calls: list[dict[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            parsed = dict(httpx.QueryParams(request.content.decode()))
            self.calls.append(parsed)
            return httpx.Response(self.status_code, json=self.body)
        if "userinfo" in str(request.url):
            return httpx.Response(200, json={"email": "person@example.com"})
        return httpx.Response(404, json={"error": "unexpected"})


@pytest.fixture
def _transport() -> Iterator[None]:
    yield
    oauth_http.set_transport_override(None)


def _install(rec: _Recorder) -> None:
    oauth_http.set_transport_override(httpx.MockTransport(rec.handler))


async def _make_connection(
    db: AsyncSession, tenant: uuid.UUID, *, expires_in: int, refresh: str | None = "r0"
) -> m.OAuthConnection:
    cid = uuid.uuid4()
    conn = m.OAuthConnection(
        id=cid,
        tenant_id=tenant,
        provider="google",
        account_label=f"{cid}@example.com",
        scopes=["email"],
        access_secret_ref=access_ref(cid),
        refresh_secret_ref=refresh_ref(cid) if refresh else None,
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=expires_in),
        status="active",
        client_source="platform",
    )
    db.add(conn)
    await db.flush()
    await store_secret(db, tenant_id=tenant, name=access_ref(cid), value="at0", kind="oauth_token")
    if refresh:
        await store_secret(
            db, tenant_id=tenant, name=refresh_ref(cid), value=refresh, kind="oauth_token"
        )
    await db.flush()
    return conn


async def test_exchange_code_parses_the_token_response(_transport: None) -> None:
    rec = _Recorder({"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600})
    _install(rec)
    got = await exchange_code(
        provider_id="google",
        client=ResolvedClient(client_id="cid", client_secret="csec", source="platform"),
        code="the-code",
        verifier="the-verifier",
        redirect_uri="https://app.example.com/api/v1/oauth/google/callback",
    )
    assert got.access_token == "at1"
    assert got.refresh_token == "rt1"
    assert got.expires_in == 3600
    sent = rec.calls[0]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "the-code"
    assert sent["code_verifier"] == "the-verifier"
    assert sent["client_id"] == "cid"


async def test_valid_token_is_returned_without_contacting_the_provider(
    app_session: AppSessionFactory, _transport: None
) -> None:
    rec = _Recorder({"access_token": "should-not-be-used"})
    _install(rec)
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _make_connection(db, tenant, expires_in=3600)
        got = await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        assert got == "at0"
        assert rec.calls == []


async def test_expired_token_triggers_a_refresh_and_persists_the_rotation(
    app_session: AppSessionFactory, _transport: None
) -> None:
    rec = _Recorder({"access_token": "at9", "refresh_token": "rt9", "expires_in": 3600})
    _install(rec)
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _make_connection(db, tenant, expires_in=-10)
        got = await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        assert got == "at9"
        assert rec.calls[0]["grant_type"] == "refresh_token"
        assert rec.calls[0]["refresh_token"] == "r0"
        # rotation persisted
        assert (await resolve_secret(db, tenant_id=tenant, ref=refresh_ref(conn.id))) == "rt9"
        assert (await resolve_secret(db, tenant_id=tenant, ref=access_ref(conn.id))) == "at9"


async def test_token_inside_the_skew_margin_is_refreshed(
    app_session: AppSessionFactory, _transport: None
) -> None:
    rec = _Recorder({"access_token": "atX", "expires_in": 3600})
    _install(rec)
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _make_connection(db, tenant, expires_in=EXPIRY_SKEW_SECONDS - 5)
        got = await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        assert got == "atX"
        assert len(rec.calls) == 1


async def test_invalid_grant_marks_the_connection_needs_reauth(
    app_session: AppSessionFactory, _transport: None
) -> None:
    rec = _Recorder({"error": "invalid_grant"}, status_code=400)
    _install(rec)
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _make_connection(db, tenant, expires_in=-10)
        with pytest.raises(OAuthReauthRequired):
            await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        await db.refresh(conn)
        assert conn.status == "needs_reauth"


async def test_non_active_connection_fails_without_a_provider_call(
    app_session: AppSessionFactory, _transport: None
) -> None:
    rec = _Recorder({"access_token": "nope"})
    _install(rec)
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _make_connection(db, tenant, expires_in=-10)
        conn.status = "revoked"
        await db.flush()
        with pytest.raises(OAuthReauthRequired):
            await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        assert rec.calls == []


async def test_connection_without_a_refresh_token_needs_reauth(
    app_session: AppSessionFactory, _transport: None
) -> None:
    rec = _Recorder({"access_token": "nope"})
    _install(rec)
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _make_connection(db, tenant, expires_in=-10, refresh=None)
        with pytest.raises(OAuthReauthRequired):
            await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        assert rec.calls == []


async def test_concurrent_refreshes_are_serialized(
    app_session: AppSessionFactory, _transport: None
) -> None:
    # The crux of the design: two syncs on one connection must not both
    # refresh, because the provider rotates the refresh token and the second
    # write would invalidate the first.
    rec = _Recorder({"access_token": "atC", "refresh_token": "rtC", "expires_in": 3600})
    _install(rec)
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _make_connection(db, tenant, expires_in=-10)
        conn_id = conn.id
        await db.commit()

    async def _one() -> str:
        async with app_session(tenant) as db:
            token = await get_access_token(db, tenant_id=tenant, connection_id=conn_id)
            await db.commit()
            return token

    # asyncio.gather's typeshed overload for two fixed args returns
    # tuple[str, str]; the runtime object is a list. `list(...)` reconciles
    # the static type with the actual value being compared below.
    results = list(await asyncio.gather(_one(), _one()))
    assert results == ["atC", "atC"]
    assert len(rec.calls) == 1, f"expected one refresh, got {len(rec.calls)}"


def test_extract_chatgpt_account_id_reads_the_claim() -> None:
    # {"https://api.openai.com/auth": {"chatgpt_account_id": "acct_abc"}}, alg=none
    id_token = (
        "eyJhbGciOiJub25lIn0."
        "eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjdF9hYmMifX0."
    )
    assert extract_chatgpt_account_id(id_token) == "acct_abc"


def test_extract_chatgpt_account_id_returns_none_for_malformed_token() -> None:
    assert extract_chatgpt_account_id("not-a-jwt") is None


def test_extract_chatgpt_account_id_returns_none_when_claim_missing() -> None:
    # {"sub": "x"}, alg=none -- well-formed JWT, no relevant claim
    id_token = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0."
    assert extract_chatgpt_account_id(id_token) is None


def test_extract_chatgpt_account_id_returns_none_when_auth_claim_is_not_a_dict() -> None:
    # {"https://api.openai.com/auth": "not-a-dict"}, alg=none -- well-formed JWT,
    # the namespace claim exists but has the wrong shape.
    id_token = "eyJhbGciOiJub25lIn0.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOiJub3QtYS1kaWN0In0."
    assert extract_chatgpt_account_id(id_token) is None


def test_extract_chatgpt_account_id_returns_none_when_account_id_is_not_a_string() -> None:
    # {"https://api.openai.com/auth": {"chatgpt_account_id": 12345}}, alg=none --
    # the claim is a dict, but chatgpt_account_id inside it is the wrong type.
    id_token = (
        "eyJhbGciOiJub25lIn0."
        "eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoxMjM0NX19."
    )
    assert extract_chatgpt_account_id(id_token) is None


async def test_get_access_token_refreshes_device_code_connection_and_updates_account_id(
    app_session: AppSessionFactory, _transport: None
) -> None:
    # {"https://api.openai.com/auth": {"chatgpt_account_id": "acct_new"}}, alg=none
    id_token = (
        "eyJhbGciOiJub25lIn0."
        "eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjdF9uZXcifX0."
    )
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CHATGPT_TOKEN_URL
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "at-new",
                "refresh_token": "rt-new",
                "expires_in": 3600,
                "id_token": id_token,
            },
        )

    oauth_http.set_transport_override(httpx.MockTransport(handler))
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        cid = uuid.uuid4()
        conn = m.OAuthConnection(
            id=cid,
            tenant_id=tenant,
            provider="openai_chatgpt",
            account_label="test@example.com",
            scopes=["openid"],
            access_secret_ref=access_ref(cid),
            refresh_secret_ref=refresh_ref(cid),
            grant_type="device_code",
            client_source="tenant",
            expires_at=datetime.now(tz=UTC) - timedelta(seconds=10),  # already stale
        )
        db.add(conn)
        await db.flush()
        await store_secret(
            db, tenant_id=tenant, name=refresh_ref(cid), value="rt-old", kind="oauth_token"
        )
        await db.flush()

        token = await get_access_token(db, tenant_id=tenant, connection_id=conn.id)

        assert token == "at-new"
        assert len(calls) == 1
        sent = calls[0]
        assert sent.headers["content-type"].startswith("application/json")  # refresh is JSON
        assert (await resolve_secret(db, tenant_id=tenant, ref=refresh_ref(cid))) == "rt-new"
        await db.refresh(conn)
        assert conn.provider_metadata["chatgpt_account_id"] == "acct_new"


async def test_get_access_token_refreshes_grok_device_code_form_encoded(
    app_session: AppSessionFactory, _transport: None
) -> None:
    from urllib.parse import parse_qs

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == GROK_TOKEN_URL
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "at-grok",
                "refresh_token": "rt-grok",
                "expires_in": 3600,
            },
        )

    oauth_http.set_transport_override(httpx.MockTransport(handler))
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        cid = uuid.uuid4()
        conn = m.OAuthConnection(
            id=cid,
            tenant_id=tenant,
            provider="xai_grok",
            account_label="acct_grok",
            scopes=["openid"],
            access_secret_ref=access_ref(cid),
            refresh_secret_ref=refresh_ref(cid),
            grant_type="device_code",
            client_source="tenant",
            expires_at=datetime.now(tz=UTC) - timedelta(seconds=10),
        )
        db.add(conn)
        await db.flush()
        await store_secret(
            db, tenant_id=tenant, name=refresh_ref(cid), value="rt-old", kind="oauth_token"
        )
        await db.flush()

        token = await get_access_token(db, tenant_id=tenant, connection_id=conn.id)

        assert token == "at-grok"
        assert len(calls) == 1
        sent = calls[0]
        assert "application/x-www-form-urlencoded" in sent.headers["content-type"]
        form = parse_qs(sent.content.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["rt-old"]
        assert (await resolve_secret(db, tenant_id=tenant, ref=refresh_ref(cid))) == "rt-grok"


async def _device_code_connection(db: AsyncSession, tenant: uuid.UUID) -> m.OAuthConnection:
    cid = uuid.uuid4()
    conn = m.OAuthConnection(
        id=cid,
        tenant_id=tenant,
        provider="openai_chatgpt",
        account_label=f"acct_{cid.hex[:8]}",
        scopes=["openid"],
        access_secret_ref=access_ref(cid),
        refresh_secret_ref=refresh_ref(cid),
        grant_type="device_code",
        client_source="tenant",
        expires_at=datetime.now(tz=UTC) - timedelta(seconds=10),  # already stale
    )
    db.add(conn)
    await db.flush()
    await store_secret(
        db, tenant_id=tenant, name=refresh_ref(cid), value="rt-old", kind="oauth_token"
    )
    await db.flush()
    return conn


async def test_device_code_refresh_marks_needs_reauth_on_invalid_grant(
    app_session: AppSessionFactory, _transport: None
) -> None:
    """`invalid_grant` is what a REVOKED or expired refresh token actually
    returns, and it is just as terminal as `refresh_token_reused`.

    Only the latter used to flip `status`; `invalid_grant` fell through to a
    generic `OAuthExchangeFailed` with the row left "active", so a
    permanently dead connection never surfaced as needing reconnection --
    it just failed identically forever. `_post_token` (the non-device-code
    refresh path in the same module) has always mapped it to
    `OAuthReauthRequired`; this mirrors that.
    """
    oauth_http.set_transport_override(
        httpx.MockTransport(lambda _r: httpx.Response(400, json={"error": "invalid_grant"}))
    )
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _device_code_connection(db, tenant)
        with pytest.raises(OAuthReauthRequired):
            await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        await db.refresh(conn)
        assert conn.status == "needs_reauth"


async def test_device_code_refresh_still_marks_needs_reauth_on_reuse(
    app_session: AppSessionFactory, _transport: None
) -> None:
    """The already-handled case, kept alongside the new one so a future edit
    cannot fix one by breaking the other."""
    oauth_http.set_transport_override(
        httpx.MockTransport(lambda _r: httpx.Response(400, json={"error": "refresh_token_reused"}))
    )
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _device_code_connection(db, tenant)
        with pytest.raises(OAuthReauthRequired):
            await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        await db.refresh(conn)
        assert conn.status == "needs_reauth"


async def test_device_code_refresh_leaves_status_active_on_a_transient_error(
    app_session: AppSessionFactory, _transport: None
) -> None:
    """A 500 is not proof the refresh token is dead -- flipping `status` on it
    would force a needless reconnect after a provider blip."""
    oauth_http.set_transport_override(
        httpx.MockTransport(lambda _r: httpx.Response(500, json={"error": "server_error"}))
    )
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _device_code_connection(db, tenant)
        with pytest.raises(OAuthExchangeFailed):
            await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
        await db.refresh(conn)
        assert conn.status == "active"


async def test_device_code_refresh_wraps_a_non_json_200(
    app_session: AppSessionFactory, _transport: None
) -> None:
    """Every other JSON-body read in this module wraps `resp.json()` in
    `OAuthExchangeFailed`; the device-code success path used to let a bare
    `ValueError` out of a non-JSON 200."""
    oauth_http.set_transport_override(
        httpx.MockTransport(lambda _r: httpx.Response(200, text="<html>not json</html>"))
    )
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        conn = await _device_code_connection(db, tenant)
        with pytest.raises(OAuthExchangeFailed):
            await get_access_token(db, tenant_id=tenant, connection_id=conn.id)
