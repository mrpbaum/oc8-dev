from __future__ import annotations

from oc8.modelrouter.adapters.grok_subscription import GrokSubscriptionAdapter
from oc8.oauth.xai_grok_params import (
    CLIENT_IDENTIFIER_HEADER,
    CLIENT_VERSION_HEADER,
    GROK_BACKEND_BASE_URL,
    TOKEN_AUTH_HEADER,
    TOKEN_AUTH_VALUE,
)


def test_headers_include_proxy_auth_and_bearer() -> None:
    adapter = GrokSubscriptionAdapter(GROK_BACKEND_BASE_URL, api_key="tok")
    headers = adapter._headers()
    assert headers["Authorization"] == "Bearer tok"
    assert headers[TOKEN_AUTH_HEADER] == TOKEN_AUTH_VALUE
    assert headers[CLIENT_VERSION_HEADER]
    assert headers[CLIENT_IDENTIFIER_HEADER] == "oc8"


def test_provider_name_and_base_url() -> None:
    adapter = GrokSubscriptionAdapter(GROK_BACKEND_BASE_URL, api_key="")
    assert adapter.provider == "xai_grok"
    assert adapter.base_url == GROK_BACKEND_BASE_URL
