"""Manual-only enforcement guard (ChatGPT subscription auth design §5).

Each test uses a fresh tenant uuid so the shared ACME tenant's rows can never
leak into the `enabled trigger` lookup, and a fresh `agent_id` uuid because
`Trigger.agent_id` carries no FK -- the guard only ever needs the id.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from oc8 import models as m
from oc8.credentials.service import create_credential
from oc8.modelrouter.subscription_guard import (
    SubscriptionModelNotManualOnly,
    assert_credential_bind_safe,
    assert_manual_only_compatible,
)
from tests.conftest import AppSessionFactory

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _kek(monkeypatch: pytest.MonkeyPatch) -> None:
    from oc8 import config

    monkeypatch.setattr(
        config.get_settings(),
        "secret_kek",
        base64.b64encode(bytes(range(32))).decode(),
        raising=False,
    )


async def _subscription_model(db: AsyncSession, tenant: uuid.UUID) -> m.ModelConfig:
    cred = await create_credential(
        db,
        tenant_id=tenant,
        name=f"cg-{uuid.uuid4().hex[:8]}",
        credential_type="openai_chatgpt_subscription",
        field_values={"oauth_connection_id": str(uuid.uuid4())},
    )
    mc = m.ModelConfig(
        tenant_id=tenant, provider="openai_chatgpt", model="gpt-5", credential_id=cred.id
    )
    db.add(mc)
    await db.flush()
    return mc


async def _api_key_model(
    db: AsyncSession, tenant: uuid.UUID, *, fallbacks: list[object] | None = None
) -> m.ModelConfig:
    cred = await create_credential(
        db,
        tenant_id=tenant,
        name=f"anthropic-{uuid.uuid4().hex[:8]}",
        credential_type="anthropic_api_key",
        field_values={"api_key": "sk-tenant"},
    )
    mc = m.ModelConfig(
        tenant_id=tenant,
        provider="anthropic",
        model="claude-sonnet-4-5",
        credential_id=cred.id,
        fallbacks=list(fallbacks or []),
    )
    db.add(mc)
    await db.flush()
    return mc


def _enabled_cron_trigger(tenant: uuid.UUID, agent_id: uuid.UUID) -> m.Trigger:
    return m.Trigger(
        tenant_id=tenant,
        agent_id=agent_id,
        kind="cron",
        task_text="x",
        cron_expression="0 * * * *",
        enabled=True,
    )


async def test_allows_when_model_is_not_subscription_type(app_session: AppSessionFactory) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        mc = m.ModelConfig(tenant_id=tenant, provider="anthropic", model="claude-sonnet-4-5")
        db.add(
            m.Trigger(
                tenant_id=tenant,
                agent_id=agent_id,
                kind="cron",
                task_text="x",
                cron_expression="0 * * * *",
                enabled=True,
            )
        )
        db.add(mc)
        await db.flush()
        # An enabled trigger is irrelevant for an API-key-backed model.
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)


async def test_allows_when_model_has_no_credential(app_session: AppSessionFactory) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        mc = m.ModelConfig(tenant_id=tenant, provider="openai", model="gpt-5", credential_id=None)
        db.add(mc)
        await db.flush()
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)


async def test_allows_when_model_config_id_is_none(app_session: AppSessionFactory) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        db.add(
            m.Trigger(
                tenant_id=tenant,
                agent_id=agent_id,
                kind="cron",
                task_text="x",
                cron_expression="0 * * * *",
                enabled=True,
            )
        )
        await db.flush()
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=None)


async def test_allows_when_model_config_row_is_missing(app_session: AppSessionFactory) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=uuid.uuid4())


async def test_allows_subscription_model_when_agent_has_no_triggers(
    app_session: AppSessionFactory,
) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        mc = await _subscription_model(db, tenant)
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)


async def test_rejects_subscription_model_when_agent_has_enabled_cron_trigger(
    app_session: AppSessionFactory,
) -> None:
    """Task 11 direction: the enabled trigger already exists, a
    subscription-backed model is about to be bound to the agent."""
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        db.add(
            m.Trigger(
                tenant_id=tenant,
                agent_id=agent_id,
                kind="cron",
                task_text="x",
                cron_expression="0 * * * *",
                enabled=True,
            )
        )
        await db.flush()
        mc = await _subscription_model(db, tenant)
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)


async def test_rejects_when_trigger_is_added_to_agent_already_on_subscription_model(
    app_session: AppSessionFactory,
) -> None:
    """Task 10 direction: the subscription model is already bound, a trigger
    is about to be created/enabled for the same agent."""
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        mc = await _subscription_model(db, tenant)
        # Guard is called with the pending trigger already flushed by the
        # caller's transaction (Task 10 creates then checks, rolling back).
        db.add(
            m.Trigger(
                tenant_id=tenant,
                agent_id=agent_id,
                kind="cron",
                task_text="x",
                cron_expression="0 * * * *",
                enabled=True,
            )
        )
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "event", "event_source": "github", "event_type": "push"},
        {"kind": "webhook"},
    ],
    ids=["event", "webhook"],
)
async def test_rejects_for_every_unattended_trigger_kind(
    app_session: AppSessionFactory, kwargs: dict[str, str]
) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    if kwargs["kind"] == "webhook":
        kwargs = {**kwargs, "webhook_token": uuid.uuid4().hex}
    async with app_session(tenant) as db:
        mc = await _subscription_model(db, tenant)
        db.add(
            m.Trigger(tenant_id=tenant, agent_id=agent_id, task_text="x", enabled=True, **kwargs)
        )
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)


async def test_ignores_disabled_triggers(app_session: AppSessionFactory) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        mc = await _subscription_model(db, tenant)
        db.add(
            m.Trigger(
                tenant_id=tenant,
                agent_id=agent_id,
                kind="cron",
                task_text="x",
                cron_expression="0 * * * *",
                enabled=False,
            )
        )
        await db.flush()
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)


async def test_ignores_enabled_triggers_of_other_agents(app_session: AppSessionFactory) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        mc = await _subscription_model(db, tenant)
        db.add(
            m.Trigger(
                tenant_id=tenant,
                agent_id=uuid.uuid4(),  # a different agent in the same tenant
                kind="cron",
                task_text="x",
                cron_expression="0 * * * *",
                enabled=True,
            )
        )
        await db.flush()
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)


async def test_error_message_names_the_cause_and_the_two_ways_out(
    app_session: AppSessionFactory,
) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        mc = await _subscription_model(db, tenant)
        db.add(
            m.Trigger(
                tenant_id=tenant,
                agent_id=agent_id,
                kind="cron",
                task_text="x",
                cron_expression="0 * * * *",
                enabled=True,
            )
        )
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly) as excinfo:
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)
    message = str(excinfo.value)
    assert "ChatGPT subscription" in message
    assert "manual" in message
    # Both remedies an operator can act on must be spelled out.
    assert "trigger" in message
    assert "API key" in message
    # The culprit may be a fallback rather than the bound model itself, so the
    # message must not send the operator looking only at the model they picked.
    assert "fallback" in message


async def test_grok_subscription_is_also_manual_only(
    app_session: AppSessionFactory,
) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        cred = await create_credential(
            db,
            tenant_id=tenant,
            name=f"gk-{uuid.uuid4().hex[:8]}",
            credential_type="xai_grok_subscription",
            field_values={"oauth_connection_id": str(uuid.uuid4())},
        )
        mc = m.ModelConfig(
            tenant_id=tenant, provider="xai_grok", model="grok-4", credential_id=cred.id
        )
        db.add(mc)
        db.add(
            m.Trigger(
                tenant_id=tenant,
                agent_id=agent_id,
                kind="cron",
                task_text="x",
                cron_expression="0 * * * *",
                enabled=True,
            )
        )
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly) as excinfo:
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=mc.id)
    assert "Grok subscription" in str(excinfo.value)


# --- Fallback-chain coverage -------------------------------------------------
# `complete_with_fallback` (oc8/modelrouter/fallback.py) silently falls through
# from the primary to each ModelConfig id in `primary.fallbacks` on a retryable
# 5xx/429/timeout. A subscription-backed model hiding in that list would run
# unattended without ever being the agent's bound model, so the guard must
# consider the whole chain, not just the primary.


async def test_rejects_when_a_fallback_is_subscription_backed(
    app_session: AppSessionFactory,
) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        sub = await _subscription_model(db, tenant)
        primary = await _api_key_model(db, tenant, fallbacks=[str(sub.id)])
        db.add(_enabled_cron_trigger(tenant, agent_id))
        await db.flush()
        # The primary itself is a perfectly ordinary API-key model.
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=primary.id)


async def test_rejects_when_a_later_fallback_is_subscription_backed(
    app_session: AppSessionFactory,
) -> None:
    """The subscription model is not the first fallback -- the whole list is
    walked, not just entry zero."""
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        innocent = await _api_key_model(db, tenant)
        sub = await _subscription_model(db, tenant)
        primary = await _api_key_model(db, tenant, fallbacks=[str(innocent.id), str(sub.id)])
        db.add(_enabled_cron_trigger(tenant, agent_id))
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=primary.id)


async def test_allows_subscription_fallback_when_agent_has_no_enabled_trigger(
    app_session: AppSessionFactory,
) -> None:
    """A subscription model in the chain is fine for a manual-only agent -- the
    fallback extension must not turn into a blanket ban on the chain."""
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        sub = await _subscription_model(db, tenant)
        primary = await _api_key_model(db, tenant, fallbacks=[str(sub.id)])
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=primary.id)


async def test_allows_when_every_fallback_is_api_key_backed(
    app_session: AppSessionFactory,
) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        other = await _api_key_model(db, tenant)
        primary = await _api_key_model(db, tenant, fallbacks=[str(other.id)])
        db.add(_enabled_cron_trigger(tenant, agent_id))
        await db.flush()
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=primary.id)


async def test_subscription_primary_still_rejects_with_fallbacks_present(
    app_session: AppSessionFactory,
) -> None:
    """Regression: the pre-existing primary-only rule still fires, unchanged,
    when the primary also carries a (harmless) fallback list."""
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        innocent = await _api_key_model(db, tenant)
        primary = await _subscription_model(db, tenant)
        primary.fallbacks = [str(innocent.id)]
        db.add(_enabled_cron_trigger(tenant, agent_id))
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=primary.id)


@pytest.mark.parametrize(
    "junk",
    ["not-a-uuid", "", None, 42, {"id": "x"}],
    ids=["nonsense", "empty", "null", "int", "dict"],
)
async def test_skips_malformed_fallback_entries(
    app_session: AppSessionFactory, junk: object
) -> None:
    """A junk entry must be skipped, not crash the guard -- and must not mask a
    real subscription-backed entry sitting after it in the same list."""
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        sub = await _subscription_model(db, tenant)
        primary = await _api_key_model(db, tenant, fallbacks=[junk, str(sub.id)])
        db.add(_enabled_cron_trigger(tenant, agent_id))
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=primary.id)


async def test_skips_fallback_ids_with_no_model_config_row(
    app_session: AppSessionFactory,
) -> None:
    """A well-formed uuid pointing at a deleted ModelConfig is skipped, exactly
    as `complete_with_fallback` skips it when building its chain."""
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        primary = await _api_key_model(db, tenant, fallbacks=[str(uuid.uuid4())])
        db.add(_enabled_cron_trigger(tenant, agent_id))
        await db.flush()
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=primary.id)


async def test_empty_and_null_fallbacks_are_both_handled(
    app_session: AppSessionFactory,
) -> None:
    tenant, agent_id = uuid.uuid4(), uuid.uuid4()
    async with app_session(tenant) as db:
        primary = await _api_key_model(db, tenant, fallbacks=[])
        db.add(_enabled_cron_trigger(tenant, agent_id))
        await db.flush()
        await assert_manual_only_compatible(db, agent_id=agent_id, model_config_id=primary.id)


# --- assert_credential_bind_safe: the model-id -> agents direction ----------
#
# `PATCH /models/{id}` names no agent at all, so `assert_manual_only_compatible`
# (which needs one) is structurally unreachable there. These cover the walk the
# other way: from one ModelConfig out to every agent that could run on it.


async def _subscription_credential(db: AsyncSession, tenant: uuid.UUID) -> m.Credential:
    return await create_credential(
        db,
        tenant_id=tenant,
        name=f"cg-{uuid.uuid4().hex[:8]}",
        credential_type="openai_chatgpt_subscription",
        field_values={"oauth_connection_id": str(uuid.uuid4())},
    )


async def _agent(
    db: AsyncSession, tenant: uuid.UUID, *, model_config_id: uuid.UUID | None
) -> m.Agent:
    agent = m.Agent(
        tenant_id=tenant,
        department_id=uuid.uuid4(),
        name=f"a-{uuid.uuid4().hex[:6]}",
        model_config_id=model_config_id,
    )
    db.add(agent)
    await db.flush()
    return agent


async def test_bind_safe_rejects_when_a_bound_agent_has_an_enabled_trigger(
    app_session: AppSessionFactory,
) -> None:
    """The bypass: an unbound `openai_chatgpt` model is legally bound to an
    agent and given a cron trigger, THEN the credential is attached."""
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        mc = m.ModelConfig(tenant_id=tenant, provider="openai_chatgpt", model="gpt-5")
        db.add(mc)
        await db.flush()
        agent = await _agent(db, tenant, model_config_id=mc.id)
        db.add(_enabled_cron_trigger(tenant, agent.id))
        cred = await _subscription_credential(db, tenant)
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_credential_bind_safe(db, model_config_id=mc.id, credential_id=cred.id)


async def test_bind_safe_rejects_when_the_model_is_only_a_fallback(
    app_session: AppSessionFactory,
) -> None:
    """The agent is bound to a DIFFERENT model that merely lists this one in
    `fallbacks` -- still reachable at runtime, still unattended."""
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        target = m.ModelConfig(tenant_id=tenant, provider="openai_chatgpt", model="gpt-5")
        db.add(target)
        await db.flush()
        primary = await _api_key_model(db, tenant, fallbacks=[str(target.id)])
        agent = await _agent(db, tenant, model_config_id=primary.id)
        db.add(_enabled_cron_trigger(tenant, agent.id))
        cred = await _subscription_credential(db, tenant)
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_credential_bind_safe(db, model_config_id=target.id, credential_id=cred.id)


async def test_bind_safe_allows_when_no_agent_reaching_it_has_a_trigger(
    app_session: AppSessionFactory,
) -> None:
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        mc = m.ModelConfig(tenant_id=tenant, provider="openai_chatgpt", model="gpt-5")
        db.add(mc)
        await db.flush()
        await _agent(db, tenant, model_config_id=mc.id)  # bound, but never scheduled
        cred = await _subscription_credential(db, tenant)
        await db.flush()
        await assert_credential_bind_safe(db, model_config_id=mc.id, credential_id=cred.id)


async def test_bind_safe_ignores_a_disabled_trigger(app_session: AppSessionFactory) -> None:
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        mc = m.ModelConfig(tenant_id=tenant, provider="openai_chatgpt", model="gpt-5")
        db.add(mc)
        await db.flush()
        agent = await _agent(db, tenant, model_config_id=mc.id)
        trigger = _enabled_cron_trigger(tenant, agent.id)
        trigger.enabled = False
        db.add(trigger)
        cred = await _subscription_credential(db, tenant)
        await db.flush()
        await assert_credential_bind_safe(db, model_config_id=mc.id, credential_id=cred.id)


async def test_bind_safe_counts_a_soft_deleted_agent(app_session: AppSessionFactory) -> None:
    """Archiving is reversible, so an archived agent still counts.

    `POST /agents/{id}/restore` brings the agent back with its triggers and its
    model binding intact and nothing in between re-runs this check, so ignoring
    archived agents made "archive -> bind the subscription credential ->
    restore" a way to land exactly the pairing this module forbids. The forward
    direction (`assert_manual_only_compatible`) never excluded archived agents;
    this side matches it.
    """
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        mc = m.ModelConfig(tenant_id=tenant, provider="openai_chatgpt", model="gpt-5")
        db.add(mc)
        await db.flush()
        agent = await _agent(db, tenant, model_config_id=mc.id)
        agent.deleted_at = datetime.now(tz=UTC)
        db.add(_enabled_cron_trigger(tenant, agent.id))
        cred = await _subscription_credential(db, tenant)
        await db.flush()
        with pytest.raises(SubscriptionModelNotManualOnly):
            await assert_credential_bind_safe(db, model_config_id=mc.id, credential_id=cred.id)


async def test_bind_safe_allows_unbinding_and_api_key_credentials(
    app_session: AppSessionFactory,
) -> None:
    """Only the subscription credential type is restricted; None (unbind) and
    an ordinary API key are always fine, however many triggers exist."""
    tenant = uuid.uuid4()
    async with app_session(tenant) as db:
        mc = m.ModelConfig(tenant_id=tenant, provider="openai_chatgpt", model="gpt-5")
        db.add(mc)
        await db.flush()
        agent = await _agent(db, tenant, model_config_id=mc.id)
        db.add(_enabled_cron_trigger(tenant, agent.id))
        api_key = await create_credential(
            db,
            tenant_id=tenant,
            name=f"openai-{uuid.uuid4().hex[:8]}",
            credential_type="openai_api_key",
            field_values={"api_key": "sk-x"},
        )
        await db.flush()
        await assert_credential_bind_safe(db, model_config_id=mc.id, credential_id=None)
        await assert_credential_bind_safe(db, model_config_id=mc.id, credential_id=api_key.id)
