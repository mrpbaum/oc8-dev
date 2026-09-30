"""Model Router — dispatches a neutral completion request to a provider adapter.

Provider resolution is deliberately forgiving so the local (Ollama) path always
works without keys: unknown providers, or Anthropic without a configured key,
fall back to the local default model.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import replace

import httpx

from oc8.config import Settings, get_settings
from oc8.modelrouter.adapters.ollama import OllamaAdapter
from oc8.modelrouter.registry import build_adapter, canonical_provider
from oc8.modelrouter.streaming import stream_with_fallback
from oc8.modelrouter.trim import overflow_tokens, trim_for_overflow
from oc8.modelrouter.types import (
    CompletionChunk,
    CompletionRequest,
    CompletionResult,
    ModelAdapter,
)
from oc8.observability import record_model_latency


def locality_for_provider(provider: str) -> str:
    """'local' if the provider string resolves to the ollama adapter via
    the existing canonical-provider mapping, else 'cloud'. Pure — does not
    consult settings/API keys, unlike ModelRouter.resolve()'s own fallback.
    That's deliberate: it means retrieval-time filtering (the caller of this
    function) is always at least as conservative as the real dispatch will
    be, never less."""
    return "local" if canonical_provider(provider) in (None, "ollama") else "cloud"


class EmbeddingUnavailable(RuntimeError):
    """Raised when the embedding backend (Ollama) is unreachable or errors."""


class ClassificationViolation(RuntimeError):
    """Raised by ModelRouter.complete() when a request carrying
    restricted-classified content would dispatch to a non-local provider
    (tech-spec §9.4 policy interception)."""


class TenantKeyRequired(RuntimeError):
    """Strict BYOK mode: a cloud completion was requested but the tenant has no
    key configured, and require_tenant_model_key is on."""


logger = logging.getLogger(__name__)


class ModelRouter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve(self, provider: str, model: str, api_key: str | None = None) -> tuple[str, str]:
        """Return the (canonical_provider, model) actually used, applying fallback.
        A per-tenant `api_key` counts toward availability, so a tenant with a key
        uses the cloud provider even when the platform env key is empty."""
        canonical = canonical_provider(provider) or "ollama"
        if canonical == "anthropic" and not (api_key or self._settings.anthropic_api_key):
            return "ollama", self._settings.default_model
        if canonical == "openai" and not (api_key or self._settings.openai_api_key):
            return "ollama", self._settings.default_model
        if canonical == "ollama":
            return "ollama", model or self._settings.default_model
        return canonical, model

    def _adapter(
        self, canonical: str, *, base_url: str | None = None, api_key: str | None = None
    ) -> ModelAdapter:
        return build_adapter(canonical, self._settings, base_url, api_key)

    def _guard_and_resolve(
        self, req: CompletionRequest
    ) -> tuple[ModelAdapter, CompletionRequest, str, str]:
        """Apply the pre-dispatch guards, then resolve adapter and request.

        Shared by complete() and stream() on purpose: a streaming path that
        re-implemented these would eventually drift, and both guards are
        security-relevant -- asking for a stream must never become a way around
        strict BYOK or the classification refusal.
        """
        # Strict BYOK: refuse a cloud request with no tenant key BEFORE the
        # availability downgrade can silently route it to ollama or the platform
        # key. Checked on the REQUESTED provider, not the resolved one.
        requested = canonical_provider(req.provider) or "ollama"
        if self._settings.require_tenant_model_key and requested != "ollama" and not req.api_key:
            if requested in {"openai_chatgpt", "xai_grok"}:
                requirement = "a connected subscription login"
            else:
                requirement = f"a per-tenant API key (credential type '{requested}_api_key')"
            raise TenantKeyRequired(
                f"provider '{requested}' requires {requirement}; none is configured for this tenant"
            )

        canonical, model = self.resolve(req.provider, req.model, req.api_key)
        if req.contains_restricted and canonical != "ollama":
            raise ClassificationViolation(
                "request contains restricted-classified content; cannot dispatch to "
                f"cloud provider '{canonical}'"
            )
        adapter = self._adapter(canonical, base_url=req.base_url, api_key=req.api_key)
        resolved = CompletionRequest(
            provider=canonical,
            model=model,
            messages=req.messages,
            tools=req.tools,
            params=req.params,
            tenant_id=req.tenant_id,
            agent_id=req.agent_id,
            request_id=req.request_id,
        )
        return adapter, resolved, canonical, model

    @staticmethod
    def _retry_trimmed(req: CompletionRequest, exc: Exception) -> CompletionRequest | None:
        """The same request with enough of the middle dropped to fit, or None.

        Only for one failure: a conversation past the model's context window,
        which the provider reports as a negative max_tokens carrying the exact
        deficit. Retrying anything else would paper over real errors, and
        retrying THIS without trimming would send an identical request.
        """
        over = overflow_tokens(str(exc))
        if over is None:
            return None
        trimmed = trim_for_overflow(req.messages, over_by=over, headroom=req.params.max_tokens)
        if trimmed is None:
            return None
        logger.warning(
            "conversation was %d tokens past the context window; retrying with %d of %d messages",
            over,
            len(trimmed),
            len(req.messages),
        )
        return replace(req, messages=trimmed)

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        adapter, resolved, canonical, model = self._guard_and_resolve(req)
        started = time.monotonic()
        try:
            try:
                return await adapter.complete(resolved)
            except Exception as exc:
                retry = self._retry_trimmed(resolved, exc)
                if retry is None:
                    raise
                return await adapter.complete(retry)
        finally:
            record_model_latency(
                provider=canonical, model=model, ms=(time.monotonic() - started) * 1000
            )

    async def stream(self, req: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        """Stream a completion, through the same guards as complete().

        Latency is recorded when the stream finishes, so the number means
        "time to full answer" exactly as it does for a non-streamed call.
        """
        adapter, resolved, canonical, model = self._guard_and_resolve(req)
        started = time.monotonic()
        try:
            sent = False
            try:
                async for chunk in stream_with_fallback(adapter, resolved):
                    sent = True
                    # Stamped here, not left to the adapter: `canonical`/`model`
                    # are what resolve() actually decided (a BYOK-missing-key
                    # downgrade included), the same source complete()'s result
                    # implicitly carries via the adapter's own `provider=self.
                    # provider`. A caller reconstructing a CompletionResult from
                    # chunks (oc8.modelrouter.accumulate) needs this to bill and
                    # cache against the model that actually ran, not the one
                    # requested.
                    chunk.provider = canonical
                    chunk.model = model
                    yield chunk
            except Exception as exc:
                # Only before anything has gone out. Once a chunk is on the wire
                # it cannot be unsent, and restarting would splice two different
                # answers together.
                retry = None if sent else self._retry_trimmed(resolved, exc)
                if retry is None:
                    raise
                async for chunk in stream_with_fallback(adapter, retry):
                    chunk.provider = canonical
                    chunk.model = model
                    yield chunk
        finally:
            record_model_latency(
                provider=canonical, model=model, ms=(time.monotonic() - started) * 1000
            )

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        """Always routed to Ollama — no per-tenant provider choice for
        embeddings in v1 (Anthropic has no embeddings API).

        `model` is a knowledge base's own `embedding_model` choice (e.g. what
        a knowledge base was created with). `"local/<tag>"` is oc8's own UI
        label for "on-prem" — Ollama has no such namespace, so the `local/`
        is stripped before the tag ever reaches it. Anything else carrying a
        `/` (`openai/text-embedding-3-large`, `google/gemini-embedding-2`) is
        a real cloud provider this v1 has no route to — refused with a plain
        EmbeddingUnavailable rather than sent to Ollama as a nonsense model
        name, where it would 404 with nothing to say why.
        """
        resolved = model or self._settings.default_embedding_model
        if "/" in resolved:
            namespace, _, tag = resolved.partition("/")
            if namespace != "local":
                raise EmbeddingUnavailable(
                    f"embedding model {resolved!r} needs a cloud provider this deployment "
                    "does not yet route embeddings through — pick a local/on-prem model"
                )
            resolved = tag
        adapter = OllamaAdapter(self._settings.ollama_base_url)
        try:
            return await adapter.embed(text, resolved)
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(str(exc)) from exc


def get_model_router() -> ModelRouter:
    return ModelRouter(get_settings())
