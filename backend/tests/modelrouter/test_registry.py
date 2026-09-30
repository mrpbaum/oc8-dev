from __future__ import annotations

from oc8.config import get_settings
from oc8.modelrouter.adapters.anthropic import AnthropicAdapter
from oc8.modelrouter.adapters.chatgpt_subscription import ChatGptSubscriptionAdapter
from oc8.modelrouter.adapters.grok_subscription import GrokSubscriptionAdapter
from oc8.modelrouter.adapters.ollama import OllamaAdapter
from oc8.modelrouter.adapters.openai import OpenAIAdapter
from oc8.modelrouter.adapters.openai_compatible import OpenAICompatibleAdapter
from oc8.modelrouter.registry import (
    _BY_CANONICAL,
    build_adapter,
    canonical_provider,
    known_providers,
)
from oc8.oauth.openai_chatgpt_params import CHATGPT_BACKEND_BASE_URL
from oc8.oauth.xai_grok_params import GROK_BACKEND_BASE_URL


def test_canonical_provider_maps_aliases_case_insensitively() -> None:
    assert canonical_provider("ollama") == "ollama"
    assert canonical_provider("Ollama") == "ollama"  # case-insensitive
    assert canonical_provider("llama") == "ollama"
    assert canonical_provider("local") == "ollama"
    assert canonical_provider("claude") == "anthropic"
    assert canonical_provider("gpt") == "openai"
    assert canonical_provider("mistral") == "openai_compatible"
    assert canonical_provider("grok") == "xai_grok"
    assert canonical_provider("nope") is None  # unknown -> None (resolve() decides the fallback)


def test_build_adapter_returns_the_same_adapter_types_as_the_old_ifelif() -> None:
    s = get_settings()
    assert isinstance(build_adapter("anthropic", s), AnthropicAdapter)
    assert isinstance(build_adapter("openai", s), OpenAIAdapter)
    assert isinstance(build_adapter("openai_compatible", s), OpenAICompatibleAdapter)
    assert isinstance(build_adapter("ollama", s), OllamaAdapter)


def test_known_providers_lists_every_canonical_with_locality() -> None:
    got = {p["canonical"]: p["locality"] for p in known_providers()}
    assert got == {
        "anthropic": "cloud",
        "openai": "cloud",
        "openai_compatible": "cloud",
        "openai_chatgpt": "cloud",
        "xai_grok": "cloud",
        "ollama": "local",
    }


def test_openai_chatgpt_provider_registered() -> None:
    assert "openai_chatgpt" in _BY_CANONICAL
    assert _BY_CANONICAL["openai_chatgpt"].locality == "cloud"


def test_openai_chatgpt_defaults_to_the_chatgpt_backend_base_url() -> None:
    """The provider carries its own base URL: nothing configures one, and the
    Responses API lives at a fixed vendor endpoint."""
    adapter = build_adapter("openai_chatgpt", get_settings())
    assert isinstance(adapter, ChatGptSubscriptionAdapter)
    assert adapter.base_url == CHATGPT_BACKEND_BASE_URL


def test_xai_grok_provider_registered() -> None:
    assert "xai_grok" in _BY_CANONICAL
    assert _BY_CANONICAL["xai_grok"].locality == "cloud"


def test_xai_grok_defaults_to_the_cli_chat_proxy() -> None:
    adapter = build_adapter("xai_grok", get_settings())
    assert isinstance(adapter, GrokSubscriptionAdapter)
    assert adapter.base_url == GROK_BACKEND_BASE_URL


def test_xai_grok_is_offered_without_any_environment_key() -> None:
    from oc8.config import Settings
    from oc8.modelrouter.registry import provider_infos

    infos = {p["canonical"]: p for p in provider_infos(Settings())}
    assert infos["xai_grok"]["available"] is True


def test_openai_chatgpt_is_offered_without_any_environment_key() -> None:
    """It is authorised per connection by a ChatGPT login, not by a
    process-wide API key -- so it must never be hidden for want of one."""
    from oc8.config import Settings
    from oc8.modelrouter.registry import provider_infos

    infos = {p["canonical"]: p for p in provider_infos(Settings())}
    assert infos["openai_chatgpt"]["available"] is True


def test_provider_infos_marks_cloud_available_only_when_key_set() -> None:
    from oc8.config import Settings
    from oc8.modelrouter.registry import provider_infos

    no_keys = Settings(anthropic_api_key="", openai_api_key="", mistral_api_key="")
    infos = {p["canonical"]: p for p in provider_infos(no_keys)}
    assert infos["ollama"]["available"] is True  # local, always usable
    assert infos["anthropic"]["available"] is False  # no key
    assert infos["openai"]["available"] is False
    assert infos["openai_compatible"]["available"] is False
    assert infos["xai_grok"]["available"] is True
    assert infos["anthropic"]["locality"] == "cloud"

    with_keys = Settings(anthropic_api_key="sk-a", openai_api_key="sk-o", mistral_api_key="sk-m")
    infos2 = {p["canonical"]: p for p in provider_infos(with_keys)}
    assert infos2["anthropic"]["available"] is True
    assert infos2["openai"]["available"] is True
    assert infos2["openai_compatible"]["available"] is True
