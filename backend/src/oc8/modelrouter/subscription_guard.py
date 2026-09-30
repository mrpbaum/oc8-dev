"""Manual-trigger-only enforcement for the `openai_chatgpt_subscription`
credential type (ChatGPT subscription auth design §5).

A personal ChatGPT Plus/Pro/Team login is not licensed for unattended or
scheduled automation -- only for manual, human-initiated runs. This module is
the server-side half of that restriction (the UI half is the models screen's
risk badge, which is advisory only); it is the single place the property is
actually enforced.

The check is called from BOTH directions, because either side of the pairing
can be the one that arrives second:

* creating or enabling a `Trigger` for an agent already bound to a
  subscription-backed model, and
* binding a subscription-backed model to an agent that already has an
  enabled `Trigger`.

Both call sites pass the same two facts -- the agent and the model config
that would be in effect -- so the logic lives here once instead of drifting
between them.

`assert_credential_bind_safe` covers a third shape the agent-plus-model pair
cannot express: binding a subscription CREDENTIAL onto an existing
`ModelConfig` (`PATCH /models/{id}`), where no agent is named at all. It
walks the opposite direction -- from one model id out to every agent that
could reach it -- so a model that is already live on unattended agents cannot
be converted into a subscription model underneath them.

Two things widen the check beyond the obvious:

* Every trigger `kind` counts, not just `cron`: `event` and `webhook` rows
  fire without a human present too, which is exactly what the licence
  excludes.
* The model side is the whole FALLBACK CHAIN, not just the bound model.
  `oc8.modelrouter.fallback` falls through from a primary to each entry of
  `ModelConfig.fallbacks` on a retryable 5xx/429/timeout, resolving each
  entry's own `credential_id` independently. A subscription model parked in
  that list would therefore run unattended without ever being the agent's
  bound model -- a bypass of this entire mechanism.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from oc8 import models as m

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: Credential types this guard restricts. ChatGPT remains the historical
#: single-type name so existing imports keep working.
SUBSCRIPTION_CREDENTIAL_TYPE = "openai_chatgpt_subscription"
SUBSCRIPTION_CREDENTIAL_TYPES = frozenset(
    {
        SUBSCRIPTION_CREDENTIAL_TYPE,
        "xai_grok_subscription",
    }
)
_SUBSCRIPTION_PRODUCT = {
    "openai_chatgpt_subscription": "ChatGPT",
    "xai_grok_subscription": "Grok",
}


class SubscriptionModelNotManualOnly(Exception):
    """Raised when a subscription-backed model and an enabled `Trigger`
    would coexist on the same agent."""

    def __init__(self, product: str = "ChatGPT") -> None:
        super().__init__(
            "This model -- or one of its fallback models, which the router "
            "switches to automatically when the first one fails -- signs in with "
            f"a personal {product} subscription. That is licensed for manual, "
            "human-started runs only, so it cannot be used by an agent that runs "
            "unattended, and this agent has at least one enabled trigger "
            "(schedule, event, or webhook). Disable or delete the agent's triggers "
            "to keep this model, or connect every model in the chain with an API "
            "key to keep the triggers."
        )


def _as_uuid(value: object) -> uuid.UUID | None:
    """Parse one `ModelConfig.fallbacks` entry, or None if it is not a uuid.

    `fallbacks` is unvalidated JSONB, so an entry can be anything. A value that
    is not a uuid cannot name a `ModelConfig`, so skipping it loses no coverage
    -- and skipping is strictly safer here than letting a `ValueError` escape a
    security check, which would turn junk data into a 500 on every model bind.
    """
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


async def _chain_configs(db: AsyncSession, model_config_id: uuid.UUID) -> list[m.ModelConfig]:
    """The ModelConfigs a completion for `model_config_id` could actually run
    on: the primary, plus one level of `primary.fallbacks`.

    This mirrors `complete_with_fallback`/`stream_completion_with_fallback`
    (oc8.modelrouter.fallback) exactly -- same one-level walk, same `db.get`
    per entry, same "skip an id with no row" rule. It deliberately does NOT
    recurse into a fallback's own `fallbacks`, because those are unreachable at
    runtime: fallback.py builds `[primary, *primary.fallbacks]` and stops. If
    fallback.py ever starts recursing, this must follow it, or a subscription
    model could hide one level deeper than the guard looks.
    """
    primary = await db.get(m.ModelConfig, model_config_id)
    if primary is None:
        return []
    configs = [primary]
    for fb_id in primary.fallbacks or []:
        fb_uuid = _as_uuid(fb_id)
        if fb_uuid is None:
            continue
        fb = await db.get(m.ModelConfig, fb_uuid)
        if fb is not None:
            configs.append(fb)
    return configs


async def _subscription_product(db: AsyncSession, configs: list[m.ModelConfig]) -> str | None:
    """Product label if ANY config in the chain is bound to a subscription
    credential, else None."""
    cred_ids = {c.credential_id for c in configs if c.credential_id is not None}
    if not cred_ids:
        return None
    stmt = (
        select(m.Credential.credential_type)
        .where(
            m.Credential.id.in_(cred_ids),
            m.Credential.credential_type.in_(SUBSCRIPTION_CREDENTIAL_TYPES),
        )
        .limit(1)
    )
    found = (await db.execute(stmt)).scalar_one_or_none()
    if found is None:
        return None
    return _SUBSCRIPTION_PRODUCT.get(found, "subscription")


async def _agent_has_enabled_trigger(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    # Any kind -- cron, event and webhook all mean "runs with nobody watching".
    # Tenant scoping comes from RLS on the `trigger` table, the same way every
    # other agent-scoped query in this package gets it.
    stmt = (
        select(m.Trigger.id)
        .where(m.Trigger.agent_id == agent_id, m.Trigger.enabled.is_(True))
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


async def assert_manual_only_compatible(
    db: AsyncSession, *, agent_id: uuid.UUID, model_config_id: uuid.UUID | None
) -> None:
    """Raise `SubscriptionModelNotManualOnly` if a completion for
    `model_config_id` could run on a ChatGPT-subscription credential while
    `agent_id` has any enabled trigger.

    "Could run on" is the whole fallback chain, not just the primary: the
    router silently falls through to `primary.fallbacks` on a retryable 5xx/
    429/timeout, so a subscription model listed there would execute unattended
    during a cron/event/webhook run without ever being the agent's bound model.

    Returns silently -- and does no more DB work than needed to establish it --
    for the overwhelmingly common cases: no model bound at all, or a chain with
    no subscription credential in it. The trigger lookup only happens once the
    chain is known to contain one.
    """
    if model_config_id is None:
        return
    product = await _subscription_product(db, await _chain_configs(db, model_config_id))
    if product is None:
        return
    if await _agent_has_enabled_trigger(db, agent_id):
        raise SubscriptionModelNotManualOnly(product)


async def _subscription_product_for_credential(
    db: AsyncSession, credential_id: uuid.UUID
) -> str | None:
    stmt = (
        select(m.Credential.credential_type)
        .where(
            m.Credential.id == credential_id,
            m.Credential.credential_type.in_(SUBSCRIPTION_CREDENTIAL_TYPES),
        )
        .limit(1)
    )
    found = (await db.execute(stmt)).scalar_one_or_none()
    if found is None:
        return None
    return _SUBSCRIPTION_PRODUCT.get(found, "subscription")


async def _model_ids_reaching(db: AsyncSession, model_config_id: uuid.UUID) -> set[uuid.UUID]:
    """Every ModelConfig id whose own chain contains `model_config_id`: itself,
    plus any config that lists it in `fallbacks`.

    The mirror image of `_chain_configs`, and it stops at the same depth for
    the same reason -- `oc8.modelrouter.fallback` builds `[primary,
    *primary.fallbacks]` and does not recurse, so a config that only reaches
    `model_config_id` through a fallback's own fallbacks cannot actually run
    on it.

    `fallbacks` is unvalidated JSONB, so the containment test is done in
    Python over the tenant's configs (a handful of rows, RLS-scoped) rather
    than as a JSONB query: a chain entry may be stored as a string, and junk
    entries must be skipped, not raise -- exactly what `_as_uuid` already does
    for the forward direction.
    """
    reaching = {model_config_id}
    configs = (await db.execute(select(m.ModelConfig))).scalars().all()
    for config in configs:
        for fb_id in config.fallbacks or []:
            if _as_uuid(fb_id) == model_config_id:
                reaching.add(config.id)
                break
    return reaching


async def assert_credential_bind_safe(
    db: AsyncSession, *, model_config_id: uuid.UUID, credential_id: uuid.UUID | None
) -> None:
    """Raise `SubscriptionModelNotManualOnly` if binding `credential_id` to
    `model_config_id` would let a ChatGPT-subscription credential run on an
    agent that has an enabled trigger.

    The bypass this closes: create an `openai_chatgpt` ModelConfig with NO
    credential, bind it to an agent, add a cron trigger (all legal -- there is
    no subscription credential in the chain yet), then PATCH the ModelConfig's
    `credential_id` to point at one. `assert_manual_only_compatible` is never
    reached on that route because no agent is named; this is that route's
    guard.

    ARCHIVED (soft-deleted) agents count here, exactly as they do in the
    forward direction (`assert_manual_only_compatible` is handed an `agent_id`
    and never asks whether that agent is deleted). Skipping them looks
    harmless -- an archived agent does not run -- but archiving is reversible,
    and `POST /agents/{id}/restore` brings the agent back with its triggers and
    its model binding intact. Excluding them made archiving a way to step out
    from under this check for the duration of one PATCH: archive the scheduled
    agent, bind the subscription credential to its model (nothing reaching it
    is visible any more), restore it, and an unattended agent is live on a
    personal subscription. The two directions must agree, and they agree by
    counting archived agents on both sides.

    Cheap for the overwhelmingly common case: unbinding (`credential_id`
    None) and any non-subscription credential return before a single agent or
    trigger row is read.
    """
    if credential_id is None:
        return
    product = await _subscription_product_for_credential(db, credential_id)
    if product is None:
        return
    reaching = await _model_ids_reaching(db, model_config_id)
    stmt = (
        select(m.Trigger.id)
        .join(m.Agent, m.Agent.id == m.Trigger.agent_id)
        .where(
            m.Trigger.enabled.is_(True),
            m.Agent.model_config_id.in_(reaching),
        )
        .limit(1)
    )
    if (await db.execute(stmt)).first() is not None:
        raise SubscriptionModelNotManualOnly(product)
