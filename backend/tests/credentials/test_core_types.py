from __future__ import annotations

import pytest

from oc8.credentials import core_types  # noqa: F401 -- import triggers registration
from oc8.credentials.registry import CORE_CREDENTIAL_TYPES


def test_anthropic_and_openai_are_registered() -> None:
    assert "anthropic_api_key" in CORE_CREDENTIAL_TYPES
    assert "openai_api_key" in CORE_CREDENTIAL_TYPES
    anthropic = CORE_CREDENTIAL_TYPES["anthropic_api_key"]
    assert [f.key for f in anthropic.fields] == ["api_key"]
    assert anthropic.fields[0].kind == "password"


def test_openai_compatible_is_registered() -> None:
    """One of the built-in cloud providers (`models.tsx`'s own provider-name
    source of truth, `oc8.modelrouter.registry._PROVIDERS`) -- `ollama` is
    excluded on purpose: it is local and has no key concept at all."""
    assert "openai_compatible_api_key" in CORE_CREDENTIAL_TYPES
    entry = CORE_CREDENTIAL_TYPES["openai_compatible_api_key"]
    assert entry.fields[0].key == "api_key"
    assert entry.fields[0].kind == "password"


def test_openai_compatible_also_declares_a_base_url_field() -> None:
    """Unlike anthropic/openai (fixed endpoints), an openai_compatible
    provider IS its base_url -- a self-hosted LiteLLM/vLLM gateway, a
    third-party proxy. Mirrors n8n's OpenAiApi credential's own `url`
    field: one named credential holds the key and the address together,
    submitted through the SAME <CredentialPicker> form -- no separate
    "server address" UI needed anywhere else."""
    entry = CORE_CREDENTIAL_TYPES["openai_compatible_api_key"]
    by_key = {f.key: f for f in entry.fields}
    assert set(by_key) == {"api_key", "base_url"}
    assert by_key["base_url"].kind == "url"


@pytest.mark.parametrize("name", ["anthropic_api_key", "openai_api_key"])
def test_fixed_endpoint_providers_have_no_base_url_field(name: str) -> None:
    entry = CORE_CREDENTIAL_TYPES[name]
    assert "base_url" not in {f.key for f in entry.fields}


def test_ollama_has_no_registered_credential_type() -> None:
    assert "ollama_api_key" not in CORE_CREDENTIAL_TYPES


@pytest.mark.parametrize(
    "name", ["anthropic_api_key", "openai_api_key", "openai_compatible_api_key"]
)
def test_display_name_is_set(name: str) -> None:
    assert CORE_CREDENTIAL_TYPES[name].display_name


def test_openai_chatgpt_subscription_registered_with_no_fields() -> None:
    spec = CORE_CREDENTIAL_TYPES["openai_chatgpt_subscription"]
    assert spec.fields == []
    assert spec.display_name == "ChatGPT subscription"


def test_xai_grok_subscription_registered_with_no_fields() -> None:
    spec = CORE_CREDENTIAL_TYPES["xai_grok_subscription"]
    assert spec.fields == []
    assert spec.display_name == "Grok subscription"
