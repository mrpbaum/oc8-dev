# oc8 Repomix AI Context Index

Generated from every XML pack in `this skill directory/` plus the project tree. Use this file first in new sessions to avoid loading multi-MB Repomix XML unnecessarily.

## How to use this index

1. Read this file.
2. For broad discovery, query `file-catalog.json` instead of reading XML packs:
   ```bash
   python3 - <<'PY'
   import json
   cat=json.load(open('file-catalog.json'))
   for f in cat['files']:
       if 'modelrouter' in f['path'] or 'models.tsx' in f['path']:
           print(f['path'], f['packs'], f.get('symbols', [])[:8])
   PY
   ```
3. Then read original source files with `read`, not the Repomix XML, unless the original file is absent.
4. If you need packed context for a whole subsystem, choose the smallest XML pack listed below.

## Generated artifacts

- `AI_CONTEXT_INDEX.md` — human routing map and load strategy.
- `file-catalog.json` — compact complete catalog of 2042 unique files extracted from all XML packs, with pack membership, line counts, hashes, and top-level symbols/headings.

## Repomix pack map

| Pack | Size | Files | Best for | Included scope |
|---|---:|---:|---|---|
| `deployment.xml` | ~101 KB | 31 | Compose/Helm/deploy/debugging containers | `docker-compose*.yml`, `.env.example`, `scripts/quickstart.sh`, `docs/DEPLOY.md`, `docs/GETTING_STARTED.md`, `deploy/helm/**`, `backend/docker/**` |
| `capas.xml` | ~284 KB | 62 | Plugin/capa manifest/discovery/export plus Odoo sample | `backend/src/oc8/capas/**`, `capas/README.md`, `capas/odoo_mcp/**` |
| `backend.xml` | ~1.1 MB | 75 | API/backend authorization/runtime intake | approvals, API, authz, runtime intake/queue, channels, `ARCHITECTURE.md` |
| `architecture-map.xml` | ~1.8 MB | 195 | High-level architecture plus selected core/UI/deploy | docs, compose, config, API, capas, frontend lib/router |
| `frontend.xml` | ~2.0 MB | 211 | UI routes/components/hooks | frontend routes/components/lib/hooks/router/package |
| `UI-API-contract.xml` | ~2.1 MB | 142 | Frontend/backend DTO/API contract | frontend lib/hooks/routes + backend api/realtime/schemas |
| `token-count-tree.xml` | ~7.8 MB | 2042 | Last resort complete tree snapshot | Nearly everything not ignored; use catalog/search first |

## Fast subsystem routing

### Model providers / LLM gateway / OpenAI-compatible behavior

Start here:
- `backend/src/oc8/modelrouter/registry.py` — built-in provider registry and plugin provider resolution.
- `backend/src/oc8/modelrouter/adapters/_openai_common.py` — shared OpenAI Chat Completions request/response translation for `openai` and `openai_compatible`.
- `backend/src/oc8/modelrouter/adapters/openai.py` — fixed OpenAI API adapter.
- `backend/src/oc8/modelrouter/adapters/openai_compatible.py` — configurable base URL adapter.
- `backend/src/oc8/modelrouter/adapters/chatgpt_subscription.py` — ChatGPT subscription Responses API adapter.
- `backend/src/oc8/modelrouter/fallback.py` — model fallback and retry behavior.
- `backend/src/oc8/modelrouter/router.py` — router service entry point.
- `backend/src/oc8/modelrouter/keys.py` — credential resolution for model calls.
- `backend/src/oc8/modelrouter/subscription_guard.py` — blocks personal ChatGPT subscription credentials on unattended triggers.
- `backend/src/oc8/api/llm_gateway.py` — oc8 as OpenAI/Anthropic/Responses-compatible gateway.
- UI: `frontend/src/routes/models.tsx`, `frontend/src/lib/hooks.ts`.
- Tests: `backend/tests/modelrouter/test_openai_adapters.py`, `backend/tests/api/test_models_crud.py`.

Relevant Repomix packs: `token-count-tree.xml` for modelrouter, `UI-API-contract.xml` for model UI/API, `frontend.xml` for UI.

### Agent execution loop / runs / MCP tools

Start here:
- `backend/src/oc8/agent/engine.py` — main `run_agent` loop, tool execution, continuation/retry handling.
- `backend/src/oc8/agent/preamble.py` — builds system prompt/run preamble.
- `backend/src/oc8/agent/control_tools.py` — built-in control tools (delegate, memory, render, approvals, status, etc.).
- `backend/src/oc8/agent/mcp_client.py` — MCP stdio/HTTP session handling.
- `backend/src/oc8/agent/mcp_pool.py` — MCP connection pooling.
- `backend/src/oc8/runtime/intake.py` — run intake.
- `backend/src/oc8/runtime/queue.py` — run queue.
- `backend/src/oc8/runtime/executor.py` — worker-side run execution (in complete catalog; not in small backend pack).
- `backend/src/oc8/api/v1/run.py` — run API.
- `backend/src/oc8/api/v1/internal_agent.py` — internal agent runtime API/gateway.
- `backend/src/oc8/api/mcp_gateway.py` and `backend/src/oc8/api/mcp_external.py` — MCP gateway surfaces.
- UI: `frontend/src/routes/agents.$id.tsx`, `frontend/src/routes/workspace.tsx`, `frontend/src/lib/hooks.ts`.

Relevant packs: `token-count-tree.xml`; partial in `backend.xml` and `UI-API-contract.xml`.

### Capas / plugins / custom providers / tool packs

Start here:
- `capas/README.md` — authoritative capa layout and behavior.
- `backend/src/oc8/capas/manifest.py` — manifest schema and parse model.
- `backend/src/oc8/capas/discovery.py` — filesystem discovery, guardrails/setup/skills/i18n/tool_pack loading.
- `backend/src/oc8/capas/contributions.py` — contribution registries (`model_adapter`, connectors, runtimes, channels, hooks, etc.).
- `backend/src/oc8/capas/service.py` — install/instantiate service.
- `backend/src/oc8/capas/export.py` — export existing config to capa artifacts.
- `backend/src/oc8/api/v1/capas.py` — Capas API.
- `frontend/src/routes/capas.tsx`, `frontend/src/components/custom-mcp-wizard.tsx` — UI for install/setup/custom MCP.
- Example: `capas/odoo_mcp/**`.

Relevant pack: `capas.xml` first, then `architecture-map.xml` or `token-count-tree.xml`.

### Auth, users, roles, permissions, PDP

Start here:
- `backend/src/oc8/api/v1/auth.py` — dev login, password setup/login, account/profile flows.
- `backend/src/oc8/authz/**` — authorization/PDP and scopes.
- `backend/src/oc8/api/v1/roles.py`, `backend/src/oc8/api/v1/users.py` — role/member APIs.
- `backend/src/oc8/models/identity.py`, `backend/src/oc8/models/roles.py` — data model (use catalog/source; not in small packs).
- UI: `frontend/src/routes/access.tsx`, `frontend/src/lib/roles-hooks.ts`, `frontend/src/lib/authz.ts`.

Relevant packs: `backend.xml`, `UI-API-contract.xml`, `token-count-tree.xml` for models.

### Departments, agents, guardrails, approvals, governance

Start here:
- `backend/src/oc8/api/v1/departments.py` — department API.
- `backend/src/oc8/api/v1/agents.py` and `agents_write.py` — agent read/write/lifecycle/model/instruction endpoints.
- `backend/src/oc8/api/v1/governance.py` — governance APIs.
- `backend/src/oc8/approvals/**` — approval domain.
- `backend/src/oc8/api/v1/approvals.py`, `clarifications.py` — approval/clarification APIs.
- `backend/src/oc8/channels/**` — approval channel integration surface.
- UI: `frontend/src/routes/departments.$id.tsx`, `frontend/src/routes/agents.$id.tsx`, `frontend/src/components/guardrail-function-rules.tsx`, `frontend/src/components/dashboard/widgets/approvals-widget.tsx`.

Relevant packs: `backend.xml`, `frontend.xml`, `UI-API-contract.xml`.

### Knowledge / documents / ingestion / search

Start here:
- `backend/src/oc8/api/v1/knowledge.py` — knowledge source/base APIs.
- `backend/src/oc8/knowledge/**` — ingestion/search/domain code (use catalog/source).
- `backend/src/oc8/api/v1/files.py` — attachments/files.
- `frontend/src/routes/knowledge.tsx` — primary UI.
- `frontend/src/lib/hooks.ts` — query/mutation hooks.

Relevant packs: `UI-API-contract.xml`, `frontend.xml`, `token-count-tree.xml`.

### Costs, budgets, metering, reconciliation

Start here:
- `backend/src/oc8/api/v1/costs.py`, `budgets.py`, `reconciliation.py`.
- `backend/src/oc8/metering/**` — usage/cost recording and reconciliation.
- `backend/src/oc8/models/pricing.py` — model price rows.
- UI: `frontend/src/routes/costs.tsx`, `frontend/src/lib/model-prices-hooks.ts`, `frontend/src/lib/reconciliation-hooks.ts`, `frontend/src/lib/costs.ts`.

Relevant packs: `UI-API-contract.xml`, `frontend.xml`, `token-count-tree.xml`.

### Deployment / operations / Docker / Helm

Start here:
- `docs/DEPLOY.md` — production Docker Compose deployment guide.
- `docker-compose.yml` — full stack, backend/worker/scheduler/provisioner/frontend/caddy/minio/postgres/redis.
- `Dockerfile.backend`, `frontend/Dockerfile`.
- `.env.example` — env vars.
- `scripts/quickstart.sh` — local quickstart.
- `deploy/helm/oc8/**` — Kubernetes chart.

Relevant pack: `deployment.xml`.

### Frontend architecture / API contracts

Start here:
- `frontend/src/lib/api.ts` — central API client.
- `frontend/src/lib/hooks.ts` — primary TanStack query/mutation hooks and DTO imports.
- `backend/src/oc8/schemas/dto.py`, `backend/src/oc8/schemas/requests.py` — backend DTO/request schemas.
- `frontend/src/router.tsx`, `frontend/src/routes/**` — TanStack router screens.
- `frontend/src/components/app-shell.tsx` — app layout/navigation.
- `frontend/src/lib/live/provider.tsx` — realtime provider.
- `backend/src/oc8/api/v1/events.py`, `backend/src/oc8/realtime/**` — backend realtime.

Relevant packs: `UI-API-contract.xml`, `frontend.xml`.

## High-value files by size/change density

These often contain the behavior you are looking for:

- `frontend/src/lib/hooks.ts` — 2922 lines; many API hooks and DTO types.
- `frontend/src/routes/agents.$id.tsx` — 2853 lines; agent detail UI.
- `frontend/src/routes/knowledge.tsx` — 2283 lines; knowledge UI.
- `backend/src/oc8/agent/control_tools.py` — 2178 lines; built-in agent tools.
- `frontend/src/routes/models.tsx` — 2044 lines; model/provider UI.
- `backend/src/oc8/agent/engine.py` — 1664 lines; execution loop.
- `backend/src/oc8/api/v1/auth.py` — 1649 lines; auth flows.
- `frontend/src/routes/costs.tsx` — 1557 lines; cost UI.
- `backend/src/oc8/api/v1/capas.py` — 1501 lines; capa API.
- `frontend/src/routes/departments.$id.tsx` — 1502 lines; department detail UI.
- `backend/src/oc8/api/llm_gateway.py` — 1266 lines; API-compatible LLM gateway.
- `backend/src/oc8/api/v1/agents_write.py` — 1215 lines; agent write endpoints.
- `backend/src/oc8/api/mcp_gateway.py` — 1093 lines; MCP gateway.
- `frontend/src/components/custom-mcp-wizard.tsx` — 1042 lines; custom MCP UI.

## Common task-to-file cheatsheet

| Task | First files to read |
|---|---|
| Fix provider request/response shape | `backend/src/oc8/modelrouter/adapters/*`, `_openai_common.py`, provider tests |
| Add a provider in core | `modelrouter/registry.py`, adapter file, credential type in `credentials/core_types.py`, UI in `routes/models.tsx` |
| Add a provider as capa | `capas/README.md`, `capas/manifest.py`, `capas/contributions.py`, example capa, possibly model adapter contribution code |
| Fix agent run behavior | `agent/engine.py`, `agent/preamble.py`, `agent/control_tools.py`, runtime executor/intake/queue |
| Fix UI calling wrong endpoint | `frontend/src/lib/hooks.ts`, `frontend/src/lib/api.ts`, matching `backend/src/oc8/api/v1/*.py`, DTO/request schemas |
| Fix access/permission denial | `authz/**`, endpoint dependency in `api/v1/*.py`, frontend `lib/authz.ts` |
| Fix approval flow | `approvals/**`, `api/v1/approvals.py`, `channels/**`, approvals widget |
| Fix Capa install/setup | `api/v1/capas.py`, `capas/discovery.py`, `capas/manifest.py`, `capas/service.py`, setup UI |
| Fix deployment env/build issue | `docker-compose.yml`, `Dockerfile.backend`, `.env.example`, `docs/DEPLOY.md`, Helm values/templates |
| Fix frontend realtime/stale state | `frontend/src/lib/live/provider.tsx`, backend `events.py`/`realtime/**`, hook invalidations in `hooks.ts` |

## Test and dev commands

Backend:
```bash
cd backend
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

Frontend:
```bash
cd frontend
npm ci
npm run lint
npm run test:unit
npm run build
```

Full pre-commit guidance is in `CONTRIBUTING.md` and `docs/contributing/coding-guidelines.md`.

## Notes for future agents

- Prefer source files over Repomix XML for edits. XML is read-only context.
- `token-count-tree.xml` is comprehensive but expensive; avoid loading it wholesale.
- `file-catalog.json` is the complete discovery layer: if a file is in any pack, it is listed there with symbols/headings.
- Repomix config excludes lockfiles, migrations, backend tests, frontend tests, generated route tree, binary assets, and public assets from most packs. Use the real repo tree for excluded files.
- Capa-specific behavior should usually live under `capas/`; core changes under `backend/src/oc8/` should satisfy the microkernel principle in `docs/contributing/architecture.md`.
