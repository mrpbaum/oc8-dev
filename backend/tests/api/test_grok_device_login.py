"""Tests for the Grok subscription device-code login endpoints."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from oc8 import models as m
from oc8.auth import get_identity_provider
from oc8.constants import ACME_TENANT_ID
from oc8.main import create_app
from oc8.oauth.device_flow import DeviceLoginStart
from oc8.oauth.errors import OAuthExchangeFailed
from oc8.oauth.tokens import TokenResponse
from oc8.oauth.xai_device_flow import DevicePollResult
from tests.conftest import AppSessionFactory

pytestmark = pytest.mark.asyncio

# Unsigned JWT with {"sub": "acct_grok"}.
_ID_TOKEN = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhY2N0X2dyb2sifQ."


@pytest.fixture(autouse=True)
def _kek(monkeypatch: pytest.MonkeyPatch) -> None:
    from oc8 import config

    monkeypatch.setattr(
        config.get_settings(),
        "secret_kek",
        base64.b64encode(bytes(range(32))).decode(),
        raising=False,
    )


def _token(role: str = "org_admin") -> str:
    return get_identity_provider().mint(
        tenant_id=uuid.UUID(str(ACME_TENANT_ID)), subject="admin-user", role=role
    )


async def test_start_returns_device_code_as_device_auth_id() -> None:
    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            headers = {"Authorization": f"Bearer {_token()}"}
            with patch(
                "oc8.api.v1.catalog.xai_device_flow.start_device_login",
                AsyncMock(
                    return_value=DeviceLoginStart(
                        device_auth_id="secret-dc",
                        user_code="ABCD-1234",
                        verification_uri="https://accounts.x.ai/device",
                        expires_in=600,
                        interval=5,
                    )
                ),
            ):
                resp = await client.post(
                    "/api/v1/models/grok-subscription/device/start", headers=headers
                )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["userCode"] == "ABCD-1234"
    assert body["deviceAuthId"] == "secret-dc"
    assert body["interval"] == 5


async def test_start_maps_oauth_failure_to_400() -> None:
    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            headers = {"Authorization": f"Bearer {_token()}"}
            with patch(
                "oc8.api.v1.catalog.xai_device_flow.start_device_login",
                AsyncMock(side_effect=OAuthExchangeFailed("device-code sign-in is not available")),
            ):
                resp = await client.post(
                    "/api/v1/models/grok-subscription/device/start", headers=headers
                )
    assert resp.status_code == 400, resp.text
    assert "not available" in resp.json()["detail"]


async def test_poll_complete_creates_grok_credential(
    app_session: AppSessionFactory,
) -> None:
    tenant = uuid.UUID(str(ACME_TENANT_ID))
    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            headers = {"Authorization": f"Bearer {_token()}"}
            future = (datetime.now(tz=UTC) + timedelta(minutes=10)).isoformat()
            with patch(
                "oc8.api.v1.catalog.xai_device_flow.poll_device_login",
                AsyncMock(
                    return_value=DevicePollResult(
                        status="complete",
                        tokens=TokenResponse(
                            access_token="at1",
                            refresh_token="rt1",
                            expires_in=3600,
                            scope=None,
                            id_token=_ID_TOKEN,
                        ),
                        error=None,
                    )
                ),
            ):
                resp = await client.post(
                    "/api/v1/models/grok-subscription/device/poll",
                    json={
                        "deviceAuthId": "secret-dc",
                        "userCode": "ABCD-1234",
                        "expiresAt": future,
                    },
                    headers=headers,
                )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "complete"
    assert body["credentialId"]

    async with app_session(tenant) as db:
        cred = await db.get(m.Credential, uuid.UUID(body["credentialId"]))
        assert cred is not None
        assert cred.credential_type == "xai_grok_subscription"
        conn = (
            await db.execute(
                select(m.OAuthConnection).where(m.OAuthConnection.provider == "xai_grok")
            )
        ).scalar_one()
        assert conn.account_label == "acct_grok"
        assert conn.grant_type == "device_code"
        assert (conn.provider_metadata or {}).get("grok_account_id") == "acct_grok"
