"""Live "what models can I pick from" lookups, one per provider family.

Separate from the adapters in `adapters/`: those speak the *completion* wire
format, this speaks each provider's *model-listing* endpoint, which is a
different shape even for two providers that share a chat-completions format
(OpenAI and an OpenAI-compatible endpoint both expose `GET /models`, but
Anthropic and Ollama each have their own).

No SSRF guard here on purpose, unlike `knowledge/connectors/fetcher.py`: that
guard exists because a document connector fetches attacker-influenced URLs on
behalf of arbitrary end users. A model provider's base_url is supplied by
whoever holds `model:manage` (an operator/admin), pointing at infrastructure
THEY chose to run (a self-hosted Ollama, an internal LiteLLM/vLLM gateway) --
the same trust level `fallback.py` already extends it at completion time.
Blocking private IPs here would break the primary Ollama use case.
"""

from __future__ import annotations

from typing import Any

import httpx

from oc8.config import Settings
from oc8.modelrouter.adapters.openai_compatible import OpenAICompatibleAdapter
from oc8.modelrouter.http_errors import raise_for_status_with_body
from oc8.modelrouter.registry import build_adapter

_TIMEOUT = 15.0


class DiscoveryError(Exception):
    """The provider could not be asked for its model list (bad key, bad
    base_url, unreachable host, ...). The message is shown to the caller."""


async def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            raise_for_status_with_body(resp)
            result: dict[str, Any] = resp.json()
            return result
    except httpx.HTTPError as exc:
        raise DiscoveryError(f"could not reach {url}: {exc}") from exc


def _entries(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = data.get(key, [])
    return raw if isinstance(raw, list) else []


async def _discover_anthropic(api_key: str | None) -> list[str]:
    if not api_key:
        raise DiscoveryError("an Anthropic API key is required to list models")
    data = await _get_json(
        "https://api.anthropic.com/v1/models",
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    return [str(item["id"]) for item in _entries(data, "data")]


async def _discover_openai_style(base_url: str, api_key: str | None) -> list[str]:
    headers = {"content-type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = await _get_json(f"{base_url.rstrip('/')}/models", headers)
    return sorted(str(item["id"]) for item in _entries(data, "data"))


async def _discover_ollama(base_url: str) -> list[str]:
    data = await _get_json(f"{base_url.rstrip('/')}/api/tags", {})
    return sorted(str(item["name"]) for item in _entries(data, "models"))


async def discover_models(
    canonical: str,
    *,
    settings: Settings,
    base_url: str | None,
    api_key: str | None,
) -> list[str]:
    """The live model list for `canonical`, using a caller-supplied key/
    base_url and falling back to the platform env config -- the same
    precedence `resolve_model_key`/`(config.params or {}).get("base_url")`
    apply at completion time.

    anthropic/openai/ollama each have their own list-models shape and are
    special-cased below. Everything else -- the built-in `openai_compatible`
    AND any plugin provider built on the same `OpenAICompatibleAdapter`
    (a LiteLLM proxy, a self-hosted vLLM gateway, ...) -- is discovered
    generically: build the REAL adapter that provider's own factory would
    (so a plugin's own default base_url, e.g. opaas_ai_provider's
    DEFAULT_BASE_URL, still applies), and if its shape is OpenAI-compatible,
    it speaks the identical `GET {base_url}/models`. A hardcoded canonical
    allowlist here would silently leave every plugin provider unsupported
    even when its wire format is one this module already knows how to ask.
    Raises `KeyError` only for a provider whose adapter isn't OpenAI-shaped
    at all (nothing to fall back to)."""
    if canonical == "anthropic":
        return await _discover_anthropic(api_key or settings.anthropic_api_key)
    if canonical == "openai":
        key = api_key or settings.openai_api_key
        return await _discover_openai_style("https://api.openai.com/v1", key)
    if canonical == "ollama":
        return await _discover_ollama(base_url or settings.ollama_base_url)
    adapter = build_adapter(canonical, settings, base_url, api_key)
    if isinstance(adapter, OpenAICompatibleAdapter):
        # Use the adapter's own headers so a subscription proxy that needs
        # more than Authorization (Grok) is asked the same way completion is.
        headers = adapter._headers()
        data = await _get_json(f"{adapter.base_url.rstrip('/')}/models", headers)
        return sorted(str(item["id"]) for item in _entries(data, "data"))
    raise KeyError(canonical)
