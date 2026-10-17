# trakrlabs: Project Scope and Development Guide

Hackathon: Graph Hacks. Track: **Agent Memory and Coordination**.
Submission deadline: **Oct 18, 2026, 9:00 PM IST** (portal closes 11:59 PM IST).

## 1. What we are building

trakrlabs is a shared, persistent memory and coordination layer for AI agents, built on FalkorDB.

Agents record what happened (**episodes**), what is currently true (**facts**) and how things are done (**procedures**) in a graph. When one agent hands a task to another, the receiver gets a package of relevant context. Any decision can be traced back to the facts and conversations it relied on. Memory survives restarts, and every tenant gets its own isolated graph.

**Demo story:** a synthetic clinic crew (Intake, Care-Plan, Discharge) hands off patient tasks without losing context. All data is synthetic.

### The test for every feature
If FalkorDB were removed, would it stop working? If not, it is decoration and does not belong in the core.

### Track focus areas and how we cover them

| Focus area | What we build | Layer |
|---|---|---|
| Episodic, semantic, procedural memory | Episode, Fact and Procedure node families | Graph, backend |
| Persistent conversation history | Session and Episode chain (`CONTAINS`, `NEXT`) surviving restarts | Graph, backend |
| Shared state and handoffs | Task node with `HANDED_OFF_TO` carrying a reason | Graph, backend, agents |
| High-concurrency reads and writes | Benchmark script with results table | Benchmark |
| Separate memory per tenant | One FalkorDB graph per tenant, chosen server-side from the API key | Backend |
| Show the path behind an answer | Trace query and trace screen | Graph, backend, frontend |

## 2. Architecture overview

```
 Agents (LangGraph)   Benchmark   Seed   Frontend (React)
          \              |         |        /
           +-------- HTTP + X-API-Key ------+
                          |
                  FastAPI backend
        routers -> services -> queries/*.cypher
                          |
                    FalkorDB
        admin graph + one graph per tenant (t_<tenant>)
```

Rules that hold across all layers:
- Only the backend talks to FalkorDB. Agents, seed, benchmark and frontend use the HTTP API.
- The graph is chosen in exactly one place (`backend/app/deps.py`) from the API key. Callers never supply a graph name.
- Cypher is parameterized and stored in `queries/*.cypher`. Never build Cypher from user input.
- Each endpoint maps to one query. No endpoint without a Cypher query behind it.

## 3. Repository layout

```
trakrlabs/
├── README.md
├── CLAUDE.md
├── docker-compose.yml
├── pyproject.toml            # one shared dependency set for all Python code
├── .venv/                    # single shared virtual environment (git-ignored)
├── .env.example
├── queries/                  # Cypher files (the six core queries + helpers)
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── deps.py
│   │   ├── schemas.py
│   │   ├── llm.py
│   │   ├── routers/
│   │   └── services/
│   └── tests/
├── seed/
├── agents/
├── benchmark/
├── frontend/src/{api,components,pages}
└── docs/
```

## 4. Layer 1: Database (FalkorDB)

### Setup
- `docker-compose.yml` runs FalkorDB: port 6379 (database), port 3000 (FalkorDB Browser), named volume `falkordb_data` for persistence.
- Status: done. Persistence across restarts verified.

### Tenancy
- One graph per tenant, named from a server-side tenant id (for example `t_northside`).
- A small **admin graph** (or Redis hash) maps API key hash to tenant id.
- Isolation guarantee: a query run on one graph cannot see another graph's data.

### Graph data model

**Nodes**

| Node | Holds | Memory type |
|---|---|---|
| Subject | id, name. The thing agents remember about (a synthetic patient) | Anchor |
| Agent | id, name, role | Coordination |
| Session | id, started time, subject | Episodic |
| Episode | id, kind (message, observation, decision), content, timestamp, idempotency_key | Episodic |
| Fact | id, attribute, value, timestamp | Semantic |
| Procedure, Step | procedure name and trigger, ordered steps | Procedural |
| Task | id, title, status | Coordination |

**Relationships**

| Relationship | Meaning |
|---|---|
| Session `CONTAINS` Episode | Conversation history |
| Episode `NEXT` Episode | Order inside a session |
| Agent `WROTE` Episode | Who recorded it |
| Fact `ABOUT` Subject | What the fact describes |
| Fact `DERIVED_FROM` Episode | Provenance: where the fact came from |
| Fact `SUPERSEDES` Fact | New value replaces old; old stays as history |
| Episode (decision) `USED` Fact or Procedure | What an agent relied on; basis of the trace |
| Procedure `HAS_STEP` Step | Ordered how-to steps |
| Procedure `LEARNED_FROM` Episode | Where the how-to knowledge came from |
| Task `FOR` Subject | What the task is about |
| Task `HANDED_OFF_TO` Agent | The handoff record (reason, time, from-agent) |

**Conflict rule:** the latest fact wins. The older fact is kept and marked superseded (nothing supersedes the current one).

### Indexes and constraints (created when a tenant graph is first created)
- Index on `id` for Subject, Episode, Fact, Task.
- Uniqueness on Episode `idempotency_key`.
- Exact syntax to be confirmed in the FalkorDB docs.

### Left out on purpose
Entity node type, importance scores, graph algorithms (PageRank, community detection), vector index.

## 5. Layer 2: Cypher queries (`queries/`)

Each file starts with a one-line comment explaining why the graph is needed. These are the queries the README links to.

| # | File | Does |
|---|---|---|
| 1 | `01_write_episode.cypher` | Create or match an episode by idempotency key, attach to session, chain with `NEXT` |
| 2 | `02_write_fact_supersede.cypher` | In one query: find current fact for subject and attribute, create new fact, link `SUPERSEDES` and `DERIVED_FROM`. No read-then-write. Same value twice creates no duplicate |
| 3 | `03_recall.cypher` | Current facts (nothing supersedes them) plus last N episodes for a subject |
| 4 | `04_fact_timeline.cypher` | Follow the `SUPERSEDES` chain for one subject and attribute, newest to oldest |
| 5 | `05_handoff_package.cypher` | For a task: subject's current facts, recent episodes, matching procedure, earlier handoff reasons |
| 6 | `06_trace.cypher` | From a decision episode, walk `USED` to facts and procedures, then `DERIVED_FROM` / `LEARNED_FROM` back to source episodes |

Supporting queries (plain, small): procedure write, procedure match by trigger, task create, handoff write, list subjects, list tasks, list decisions, stats counts.

**Done when:** all six return correct results in FalkorDB Browser against seed data, with the duplicate-write and supersede checks passing.

## 6. Layer 3: Backend (FastAPI)

### Stack
Python, FastAPI, `falkordb` client, Pydantic, one LLM provider, pytest. No queue and no Temporal: fact extraction runs as a FastAPI background task.

### Module responsibilities

| File | Responsibility |
|---|---|
| `main.py` | App creation, router registration |
| `config.py` | Environment settings (admin secret, LLM key, DB host) |
| `db.py` | FalkorDB client, tenant graph lookup, index and constraint setup |
| `deps.py` | Reads `X-API-Key`, finds the tenant, returns that tenant's graph handle. The only place a graph name is chosen |
| `schemas.py` | Pydantic request and response models |
| `llm.py` | The one LLM provider behind one function |
| `routers/` | HTTP only, no graph logic |
| `services/` | Load a `.cypher` file, run it on the tenant graph, shape the result |

### Endpoints (each maps to a query)

| Endpoint | Does |
|---|---|
| `POST /admin/tenants` | Create a tenant graph and return its API key (protected by an env secret) |
| `POST /v1/sessions` | Start a session for a subject and agent |
| `POST /v1/episodes` | Write an episode, safe to retry via idempotency key |
| `POST /v1/facts` | Write a fact, superseding the old value |
| `GET /v1/subjects/{id}/recall` | Current facts and recent episodes |
| `GET /v1/subjects/{id}/facts/{attribute}/timeline` | Fact history |
| `POST /v1/procedures` | Save a procedure with steps and source episode |
| `GET /v1/procedures/match` | Find a procedure by trigger |
| `POST /v1/tasks` | Create a task for a subject |
| `POST /v1/tasks/{id}/handoff` | Hand a task to another agent with a reason |
| `GET /v1/tasks/{id}/package` | Context the receiving agent gets |
| `GET /v1/decisions/{episode_id}/trace` | Why a decision was made (also returns the Cypher it ran) |
| `GET /v1/stats` | Counts by memory type, tasks by status |
| `GET /v1/subjects`, `/v1/tasks`, `/v1/decisions` | Plain list endpoints for the UI |

### Consolidation (fact extraction)
After an episode is written, a background task sends its text to the LLM with a small Pydantic schema (`subject`, `attribute`, `value`) and writes each result through the same fact logic. If the LLM fails or returns invalid output, the episode is still stored and the failure is logged. Agents can also write facts directly, so the demo never depends on LLM reliability.

### Tests (`backend/tests/`)
1. **Tenant leak:** tenant A's key can never read tenant B's data.
2. **Restart persistence:** write, restart API and FalkorDB, recall returns the same data.
3. **Idempotency:** the same episode sent twice stores once.
4. **Supersede:** a changed fact leaves one current value and one superseded value.

### Left out on purpose
User accounts, roles, rate limiting, pagination beyond a simple limit, websockets, second LLM provider. MCP server and vector search are stretch goals only.

## 7. Layer 4: Seed data (`seed/`)

- Two tenants: Northside Clinic and Lakeview Health.
- The **same patient ids** in both tenants, so isolation is visible.
- 5 to 8 synthetic patients, an agent per role, sessions, episodes, and facts with at least one superseded.
- Synthetic data only. Never real patient or personal data.
- Final form goes through the API and the admin endpoint, so it exercises the real tenant logic.

## 8. Layer 5: Agents (`agents/`)

| File | Role |
|---|---|
| `client.py` | Thin wrapper over the backend API |
| `tools.py` | Tools: recall, write episode, write fact, create task, hand off, get package, save procedure |
| `intake.py` | Talks to the patient, records episodes and facts |
| `care_plan.py` | Receives the handoff, applies a procedure, records a decision episode |
| `discharge.py` | Starts later in a fresh process, reads everything, continues |
| `run_demo.py` | Runs the demo script end to end |

LangGraph runs each agent's reasoning loop. It does not own memory; all state that must survive lives in FalkorDB. A one-line notice states that agents coordinate care and give no medical advice.

### Demo script (this is the video)
1. Intake talks to a synthetic patient and records episodes and a fact: preferred contact is phone.
2. Intake creates a task and hands it to Care-Plan with a reason.
3. Care-Plan reads the handoff package, applies the missed-appointment procedure, and writes a decision episode pointing to what it used.
4. The patient later says to use email. The fact is superseded; the timeline shows both values.
5. Stop and restart the API and the FalkorDB container.
6. Discharge starts as a new process, recalls the patient, and continues without asking anything again.
7. The trace for Discharge's decision shows the chain back to the original episodes.
8. A second tenant's key sees none of it.

## 9. Layer 6: Benchmark (`benchmark/`)

One plain `asyncio` + `httpx` script. Three runs:
1. Many agents reading one tenant.
2. Many agents writing one tenant.
3. Mixed load across five tenants in parallel.

Record p50 and p95 latency, throughput and errors for each run. **Correctness check:** 20 concurrent writes to the same subject and attribute must leave exactly one current fact. Report results as measured; if one tenant's writes are the bottleneck, say so and show that parallel tenants scale. The table goes in the README with the machine and FalkorDB setup noted.

## 10. Layer 7: Frontend (`frontend/`)

Purpose: make the graph's work visible. It only reads from the API and is not what satisfies the graph requirement.

Stack: React, TypeScript (strict), Tailwind, React Flow. Desktop only, one theme.

| Screen | Shows | Uses |
|---|---|---|
| Sign-in | API key field; tenant name shown in the header afterwards | `/v1/stats` |
| Subject memory | Subject picker; current facts, recent episodes, linked procedures | recall |
| Fact timeline | Values of one attribute over time; superseded values greyed, each linking to its source episode | timeline |
| Handoffs | Task list with state; from-agent, to-agent, reason, and the package | tasks, package |
| Trace (hero) | Decision left, facts and procedures used in the middle, source episodes right, edges labeled `USED` and `DERIVED_FROM`; collapsible panel with the Cypher | trace |

Colors by memory type: episodic blue, semantic green, procedural amber, handoffs purple.
API key kept in memory for the session only; 401 returns to sign-in.

Left out: dashboard charts, agent directory, procedures library, conflict review, tenant admin screen, benchmark UI, dark mode, mobile layout, settings.

## 11. Layer 8: Deployment

- FalkorDB: FalkorDB Cloud if the plan fits, otherwise Docker on a small VPS.
- API: any container host (Railway, Fly.io, Render). UI: Vercel or the same host.
- Secrets (LLM key, admin secret, DB password) live in environment variables, never in the repo.
- Pre-create two demo tenants with synthetic data and put their keys in the README.
- Deploy a bare API early, not on the last day.
- Fallback: one-command `docker compose up` for the whole stack plus the demo video.
- Set a database password before any public deployment.

## 12. Layer 9: Documentation and submission

README sections, in order:
1. One-paragraph pitch and the track entered.
2. Architecture diagram.
3. Graph data model (tables or diagram).
4. The Cypher queries the product depends on, each with one line on why the graph is needed.
5. Setup: local with Docker Compose, and the live deployment link.
6. Benchmark results table, and the isolation and restart tests.
7. AI-assistant disclosure: which tools were used and for what.
8. Known limits (honest list).

Demo video (3 to 4 minutes): handoff, fact change, restart, trace, second tenant. Show the Cypher panel once and the benchmark table once. Say what happens if FalkorDB is removed.

### Submission checklist
- [ ] Public repo with the README
- [ ] `queries/` folder with explained Cypher
- [ ] Demo video link
- [ ] Live deployment link, or full local setup instructions
- [ ] Track named: Agent Memory and Coordination
- [ ] AI coding assistant use disclosed
- [ ] Only synthetic data in the repo and the graph
- [ ] No keys or secrets committed
- [ ] Submitted through the WeMakeDevs panel before 9:00 PM IST

## 13. Build order and gates

| # | Block | Gate (must pass before moving on) |
|---|---|---|
| 1 | Foundation: Docker, Python env, isolation check, indexes, constraint | Two tenants cannot read each other; duplicate idempotency key rejected |
| 2 | Seed + queries 1 to 4 | Idempotent write, correct supersede chain, correct recall and timeline |
| 3 | Queries 5 and 6, procedure write and match | All six correct in FalkorDB Browser |
| 4 | Backend core: config, db, deps, admin endpoint, schemas | API key resolves to the right tenant graph |
| 5 | Endpoints | All endpoints work via the OpenAPI docs page |
| 6 | Consolidation | "I moved to Delhi" produces a superseding fact within seconds |
| 7 | Tests | The four tests pass |
| 8 | Agents | Demo script runs end to end twice with no manual fixes |
| 9 | Benchmark | One command produces the table; same-attribute check passes |
| 10 | Frontend | All five screens work against demo data; trace shows the Cypher |
| 11 | Deploy | Live link works, or compose fallback verified |
| 12 | README, video, rehearsal, submit | Checklist complete before 9:00 PM IST |

**Never cut:** one graph per tenant with the leak test, handoff with its package, the trace query and screen, restart persistence.

## 14. Constraints and rules to remember

- Only synthetic data. No real patient or personal data in the graph.
- Every member must be able to explain the model, queries and architecture (rules 12 and 13).
- AI assistance is disclosed in the README. The owner writes the code; AI is used for suggestions, review and any parts explicitly handed off, and those are listed in the disclosure.
- Out of scope: custom orchestration or retry engine, Temporal, decay and importance scoring, conflict review queue, user accounts, billing, roles, multiple LLM providers, automatic procedure mining.

## 15. Risks

| Risk | Response |
|---|---|
| Concurrent writes to one graph are slow or race on the same fact | Supersede in a single query. Run the same-attribute check early. Report numbers honestly |
| LLM extraction is unreliable | Small Pydantic schema; failures never block episode writes; agents can write facts directly |
| Deployment surprises on the last day | Deploy a bare API early; keep the Docker Compose fallback working |
| Cypher takes longer than planned | Practice on the scratch graph; ask in the FalkorDB Discord |
| Over-building | Check each feature against the "if FalkorDB were removed" test and the left-out lists |
| Unable to explain AI-written code | Write the Cypher and core services yourself; disclose AI use |
| Python 3.14 package compatibility | If an install fails, use Python 3.12 or 3.13 and update `requires-python` |
