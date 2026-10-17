# trakrlabs

Agent memory and coordination layer on FalkorDB (graph per tenant).

## How we work (most important)
- The owner writes the code. Claude suggests, explains and reviews.
- Do NOT create or edit project files unless explicitly asked to implement a specific part.
- When asked to implement: simple, readable, human-style code. No extra abstractions.
- Every member must be able to explain the model, queries and architecture to judges.
- AI assistance is disclosed in the README. Flag anything that should be mentioned.

## Rules that must hold
- One FalkorDB graph per tenant. The graph is chosen only in `backend/app/deps.py`
  from the API key. Callers never supply a graph name.
- Cypher is parameterized and lives in `queries/*.cypher`. Never build Cypher from user input.
- Each endpoint maps to exactly one query. No endpoint without a Cypher query behind it.
- Agents, seed and benchmark talk to the API only, never to FalkorDB directly.
- Synthetic data only. No real personal data. No secrets committed.
- Conflict rule: the latest fact wins, the older one is marked SUPERSEDED.

## Structure
- `queries/`          Cypher files (the six core queries)
- `backend/app/`      FastAPI: config, db, deps, schemas
  - `routers/`        HTTP only
  - `services/`       run a query, shape the result
- `backend/tests/`    leak, restart, idempotency, supersede
- `seed/`             synthetic data for two tenants
- `agents/`           LangGraph demo crew (Intake, Care-Plan, Discharge)
- `benchmark/`        asyncio + httpx load test
- `frontend/src/`     React + TS + Tailwind + React Flow (api, components, pages)
- `docs/`             architecture and data model

## Graph model
Nodes: Subject, Agent, Session, Episode, Fact, Procedure, Step, Task
Relationships: CONTAINS, NEXT, WROTE, ABOUT, DERIVED_FROM, SUPERSEDES, USED,
HAS_STEP, LEARNED_FROM, FOR, HANDED_OFF_TO

## Commands
- Start DB/API: `docker compose up`
- Tests: `cd backend && pytest`
- Seed: `python seed/seed.py`
- Benchmark: `python benchmark/bench.py`

## Out of scope (do not suggest)
Custom orchestration or retry engine, Temporal, decay/importance scoring, conflict review queue,
user accounts/billing/roles, multiple LLM providers, auto procedure mining, dark mode.
MCP server and vector search are stretch goals only, after everything else is done.

## Code style
- Python: type hints, ruff formatting, small functions.
- TypeScript: strict mode.
- Comments only where the why is not obvious.
