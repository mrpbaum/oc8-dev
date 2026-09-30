"""Tests for the xAI Grok RFC 8628 device-code client."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from urllib.parse import parse_qs

import httpx
import pytest

from oc8.oauth import http as oauth_http
from oc8.oauth import xai_device_flow
from oc8.oauth.errors import OAuthExchangeFailed
from oc8.oauth.xai_grok_params import (
    CLIENT_ID,
    DEVICE_AUTHORIZATION_URL,
    DEVICE_GRANT_TYPE,
    TOKEN_URL,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _transport() -> Iterator[None]:
    yield
    oauth_http.set_transport_override(None)


def _install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
    oauth_http.set_transport_override(httpx.MockTransport(handler))


async def test_start_device_login_parses_form_response(_transport: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == DEVICE_AUTHORIZATION_URL
        form = parse_qs(request.content.decode())
        assert form["client_id"] == [CLIENT_ID]
        assert "grok-cli:access" in form["scope"][0]
        return httpx.Response(
            200,
            json={
                "device_code": "secret-dc",
                "user_code": "ABCD-1234",
                "verification_uri": "https://accounts.x.ai/device",
                "verification_uri_complete": "https://accounts.x.ai/device?user_code=ABCD-1234",
                "expires_in": 600,
                "interval": 5,
            },
        )

    _install(handler)
    result = await xai_device_flow.start_device_login()
    assert result.device_auth_id == "secret-dc"
    assert result.user_code == "ABCD-1234"
    assert result.verification_uri == "https://accounts.x.ai/device?user_code=ABCD-1234"
    assert result.expires_in == 600
    assert result.interval == 5


async def test_start_device_login_404_is_not_enabled(_transport: None) -> None:
    _install(lambda request: httpx.Response(404))
    with pytest.raises(OAuthExchangeFailed, match="not available"):
        await xai_device_flow.start_device_login()


async def test_poll_pending_on_authorization_pending(_transport: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == [DEVICE_GRANT_TYPE]
        assert form["device_code"] == ["secret-dc"]
        assert form["client_id"] == [CLIENT_ID]
        return httpx.Response(400, json={"error": "authorization_pending"})

    _install(handler)
    result = await xai_device_flow.poll_device_login("secret-dc")
    assert result.status == "pending"
    assert result.tokens is None


async def test_poll_expired_token(_transport: None) -> None:
    _install(lambda request: httpx.Response(400, json={"error": "expired_token"}))
    result = await xai_device_flow.poll_device_login("secret-dc")
    assert result.status == "expired"


async def test_poll_complete_returns_tokens(_transport: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "at1",
                "refresh_token": "rt1",
                "expires_in": 3600,
                "id_token": "id.jwt",
            },
        )

    _install(handler)
    result = await xai_device_flow.poll_device_login("secret-dc")
    assert result.status == "complete"
    assert result.tokens is not None
    assert result.tokens.access_token == "at1"
    assert result.tokens.refresh_token == "rt1"
