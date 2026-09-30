"""xAI "Sign in with Grok" device-code OAuth parameters.

Sourced from xAI's own public grok CLI, read from xai-org/grok-build at
main (2026-09-30):

  - crates/codegen/xai-grok-login/src/config.rs
    ``XAI_OAUTH2_ISSUER``, default client id, ``default_oauth2_scopes``,
    ``DEFAULT_OAUTH2_REFERRER``
  - crates/codegen/xai-grok-login/src/device_code.rs
    RFC 8628 device start and token poll
  - crates/codegen/xai-grok-login/src/oidc/protocol.rs
    form-encoded ``refresh_token`` grant
  - crates/codegen/xai-grok-env/src/lib.rs
    ``PROD_CLI_CHAT_PROXY_BASE_URL`` = ``https://cli-chat-proxy.grok.com/v1``
  - crates/codegen/xai-grok-shell/src/agent/proxy_headers.rs
    headers the subscription proxy requires besides ``Authorization``

This is a standard device-code grant, not OpenAI's bespoke Codex flow.
Do not reuse ``oc8.oauth.device_flow`` for it.
"""

from __future__ import annotations

# config.rs default OAuth2ProviderConfig client_id (public, no secret).
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"

ISSUER = "https://auth.x.ai"
DEVICE_AUTHORIZATION_URL = f"{ISSUER}/oauth2/device/code"
TOKEN_URL = f"{ISSUER}/oauth2/token"

# device_code.rs DEVICE_GRANT_TYPE.
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

# config.rs DEFAULT_OAUTH2_REFERRER. The IdP records it; the official client
# sends this exact value.
REFERRER = "grok-build"

# config.rs default_oauth2_scopes, the frozen personal-login set.
DEFAULT_SCOPES: tuple[str, ...] = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "grok-cli:access",
    "api:access",
    "conversations:read",
    "conversations:write",
    "workspaces:read",
    "workspaces:write",
)

# xai-grok-env PRODUCTION_ENDPOINTS.cli_chat_proxy_base_url. Chat Completions
# live at ``{base}/chat/completions``; the model list is ``{base}/models``.
GROK_BACKEND_BASE_URL = "https://cli-chat-proxy.grok.com/v1"

# xai-grok-shell Cargo.toml version on the same commit the constants above
# were read from. The proxy version-gate requires ``x-grok-client-version``.
GROK_CLIENT_VERSION = "1.0.45"

# proxy_headers.rs, sent on every cli-chat-proxy call.
TOKEN_AUTH_HEADER = "X-XAI-Token-Auth"
TOKEN_AUTH_VALUE = "xai-grok-cli"
AUTHENTICATE_RESPONSE_HEADER = "x-authenticateresponse"
AUTHENTICATE_RESPONSE_VALUE = "authenticate-response"
CLIENT_VERSION_HEADER = "x-grok-client-version"
CLIENT_IDENTIFIER_HEADER = "x-grok-client-identifier"
CLIENT_IDENTIFIER = "oc8"
CLIENT_MODE_HEADER = "x-grok-client-mode"
CLIENT_MODE = "interactive"
CLIENT_SURFACE_HEADER = "x-grok-client-surface"
CLIENT_SURFACE = "ui"
