"""xAI Grok subscription device-code client.

RFC 8628, as grok-build's ``device_code.rs`` implements it: form-encoded
start, form-encoded poll of the token endpoint, pending signaled by
``authorization_pending`` rather than HTTP 403. Not the OpenAI Codex flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from oc8.oauth.device_flow import DeviceLoginStart
from oc8.oauth.errors import OAuthExchangeFailed
from oc8.oauth.http import get_client
from oc8.oauth.tokens import TokenResponse, _parse
from oc8.oauth.xai_grok_params import (
    CLIENT_ID,
    CLIENT_SURFACE,
    CLIENT_SURFACE_HEADER,
    CLIENT_VERSION_HEADER,
    DEFAULT_SCOPES,
    DEVICE_AUTHORIZATION_URL,
    DEVICE_GRANT_TYPE,
    GROK_CLIENT_VERSION,
    REFERRER,
    TOKEN_URL,
)

_PENDING = frozenset({"authorization_pending", "slow_down"})


@dataclass(frozen=True)
class DevicePollResult:
    status: Literal["pending", "complete", "expired", "error"]
    tokens: TokenResponse | None
    error: str | None


def _headers() -> dict[str, str]:
    return {
        CLIENT_VERSION_HEADER: GROK_CLIENT_VERSION,
        CLIENT_SURFACE_HEADER: CLIENT_SURFACE,
    }


async def start_device_login() -> DeviceLoginStart:
    """Start a Grok device login.

    The secret ``device_code`` is returned as ``device_auth_id`` so the
    existing stateless poll DTO (which echoes that field back) can carry it.
    ``user_code`` is what the person types; the poll does not need it.
    """
    async with get_client() as client:
        resp = await client.post(
            DEVICE_AUTHORIZATION_URL,
            data={
                "client_id": CLIENT_ID,
                "scope": " ".join(DEFAULT_SCOPES),
                "referrer": REFERRER,
            },
            headers=_headers(),
        )
    if resp.status_code == 404:
        raise OAuthExchangeFailed("device-code sign-in is not available for this xAI deployment")
    if resp.status_code >= 400:
        raise OAuthExchangeFailed(f"device authorization request failed ({resp.status_code})")
    try:
        body: dict[str, object] = resp.json()
    except ValueError:
        raise OAuthExchangeFailed("device authorization endpoint returned non-JSON") from None
    device_code = body.get("device_code")
    user_code = body.get("user_code")
    verification_uri = body.get("verification_uri_complete") or body.get("verification_uri")
    expires_in = body.get("expires_in")
    interval = body.get("interval", 5)
    if not isinstance(device_code, str) or not isinstance(user_code, str):
        raise OAuthExchangeFailed(
            "device authorization response is missing device_code or user_code"
        )
    if not isinstance(verification_uri, str) or not verification_uri.startswith("https://"):
        raise OAuthExchangeFailed("device authorization response has no https verification URI")
    if not isinstance(expires_in, int | float | str) or not isinstance(interval, int | float | str):
        raise OAuthExchangeFailed(
            "device authorization response has a non-numeric expiry or interval"
        )
    return DeviceLoginStart(
        device_auth_id=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        expires_in=int(expires_in),
        interval=max(1, int(interval)),
    )


async def poll_device_login(device_code: str, _user_code: str = "") -> DevicePollResult:
    """One poll. ``_user_code`` is unused; the catalog poll body still sends it."""
    async with get_client() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": DEVICE_GRANT_TYPE,
                "device_code": device_code,
                "client_id": CLIENT_ID,
            },
            headers=_headers(),
        )
    if resp.status_code < 400:
        try:
            body: dict[str, object] = resp.json()
        except ValueError:
            return DevicePollResult(status="error", tokens=None, error="non-JSON token response")
        try:
            tokens = _parse(body)
        except OAuthExchangeFailed as exc:
            return DevicePollResult(status="error", tokens=None, error=str(exc))
        return DevicePollResult(status="complete", tokens=tokens, error=None)
    try:
        err: dict[str, object] = resp.json()
    except ValueError:
        return DevicePollResult(status="error", tokens=None, error=f"http {resp.status_code}")
    code = err.get("error")
    if code in _PENDING:
        return DevicePollResult(status="pending", tokens=None, error=None)
    if code == "expired_token":
        return DevicePollResult(status="expired", tokens=None, error=None)
    detail = err.get("error_description")
    if isinstance(detail, str) and detail:
        message = detail
    elif isinstance(code, str):
        message = code
    else:
        message = f"http {resp.status_code}"
    return DevicePollResult(status="error", tokens=None, error=str(message))
