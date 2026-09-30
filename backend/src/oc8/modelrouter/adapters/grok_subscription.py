"""Grok subscription adapter.

The subscription proxy (``https://cli-chat-proxy.grok.com/v1``) speaks
OpenAI Chat Completions. Auth is a bearer token from the device-code
login, plus the proxy headers grok-build sends on every call. This is
not the Responses-only Codex backend, so the wire translation is the
shared OpenAI-compatible one.
"""

from __future__ import annotations

from oc8.modelrouter.adapters.openai_compatible import OpenAICompatibleAdapter
from oc8.oauth.xai_grok_params import (
    AUTHENTICATE_RESPONSE_HEADER,
    AUTHENTICATE_RESPONSE_VALUE,
    CLIENT_IDENTIFIER,
    CLIENT_IDENTIFIER_HEADER,
    CLIENT_MODE,
    CLIENT_MODE_HEADER,
    CLIENT_VERSION_HEADER,
    GROK_CLIENT_VERSION,
    TOKEN_AUTH_HEADER,
    TOKEN_AUTH_VALUE,
)


class GrokSubscriptionAdapter(OpenAICompatibleAdapter):
    provider = "xai_grok"

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers[CLIENT_VERSION_HEADER] = GROK_CLIENT_VERSION
        headers[CLIENT_IDENTIFIER_HEADER] = CLIENT_IDENTIFIER
        headers[TOKEN_AUTH_HEADER] = TOKEN_AUTH_VALUE
        headers[AUTHENTICATE_RESPONSE_HEADER] = AUTHENTICATE_RESPONSE_VALUE
        headers[CLIENT_MODE_HEADER] = CLIENT_MODE
        return headers
