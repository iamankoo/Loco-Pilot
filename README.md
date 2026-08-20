# LocoPilot

LocoPilot is an autonomous AI software engineering agent. It accepts a
software task and a repository, understands the codebase, plans an
implementation, modifies code through controlled tools, runs tests,
diagnoses and fixes failures, reviews the resulting diff, and returns a
structured engineering result. It is not a chatbot — there is no
conversational interface; the unit of interaction is a task submitted to
an execution.

## Status: Phase 1.3 — Agent Brain + Repository Intelligence

Phases 1.1 (FastAPI/config/DB/Redis/LLM foundation) and 1.2 (persistence +
controlled tool system) are done. This milestone adds the actual
intelligence: a LangGraph-orchestrated multi-agent pipeline and a real RAG
pipeline over the repository, both wired to Phase 1.2's persistence and
tool layers. It does **not** yet include a Docker execution sandbox, real
test/build execution, or a dashboard — see Known Limitations.

What's implemented:

- A typed LangGraph state machine (`agents/state.py`, `agents/graph.py`):
  Orchestrator → Planner → Developer → Tester → (Debugger loop | Reviewer)
  → finalize, with bounded retries and explicit error routing
- Six agent roles (`agents/{planner,developer,tester,debugger,reviewer}.py`
  + the Orchestrator's init/finalize nodes in `agents/graph.py`), each with
  structured Pydantic input/output, a restricted tool permission set, and
  real LLM calls when an LLM is configured
- A provider-agnostic structured-LLM boundary (`agents/llm_client.py`)
  built on the existing `backend.app.core.llm` provider abstraction —
  Qwen3-Coder (hosted or a local OpenAI-compatible endpoint) stays a
  config change, never agent code
- A real repository RAG pipeline: file discovery/filtering → chunking →
  embedding → pgvector storage → cosine-similarity retrieval → a
  size-bounded, deduplicated context builder (`rag/`)
- A pluggable embedding provider abstraction (`rag/embeddings/`): a free,
  local, deterministic default (no API key, no download) plus an
  OpenAI-compatible provider for a real semantic model later
- The `repository_chunks` pgvector table + Alembic migration, and an
  execution service (`backend/app/services/execution_service.py`) that is
  the sole boundary between the API and LangGraph
- `POST /api/v1/executions` / `GET /api/v1/executions/{id}` — the only way
  to trigger agent activity over HTTP; still no arbitrary tool/command
  endpoint anywhere in the API

## LangGraph architecture

```
START → orchestrator → planner → developer → tester ─┬─ (failed, retries left) → debugger → developer (loop)
                                                       └─ (passed | unavailable | retries exhausted) → reviewer
reviewer → finalize → END
```

- **Orchestrator** (graph init node): receives the task, retrieves RAG
  context for it, and initializes state — no LLM call; this is
  deterministic setup/routing, not reasoning.
- **Planner**: read-only. Produces a structured `Plan` (objective,
  assumptions, files involved, steps, testing strategy, risks) from the
  task + retrieved repository context. Never writes files.
- **Developer**: reads the plan's named files for real before proposing
  anything, asks the LLM for a structured `DeveloperPlan` (edits/writes),
  then applies each one via real, permission-checked, persisted tool
  calls. `files_changed` reflects only what actually happened — a failed
  `edit_file` call is recorded as `change_type="failed"`, never silently
  dropped or reported as success.
- **Tester**: checks whether it actually has an execute-capable tool
  available. Today it never does (no sandbox exists yet), so it reports
  `status="unavailable"` deterministically, with **no LLM call** — there
  is nothing for an LLM to interpret when no test ran, and asking one
  invites exactly the fabricated-result failure mode this system must
  avoid. The `status="passed"/"failed"` path is real code, exercised in
  tests via a fake execute-capable tool, ready for Phase 1.4.
- **Debugger**: read-only in practice (granted write permission per the
  spec's permission table, but this implementation only diagnoses).
  Produces a structured `DebugResult` (root cause, proposed fix,
  confidence) and hands it back to Developer via the state's message
  trail — it never edits a file itself.
- **Reviewer**: pulls the actual `git diff` (a real tool call) rather than
  trusting summaries, and asks the LLM for a structured `ReviewResult`
  (`approved` / `changes_required` + issues). Never modifies files.
- **finalize**: builds a `final_result` summary from whatever state the
  run actually reached and is the only path to `END`.

Retries are bounded by `MAX_DEBUG_RETRIES` (default 2, env-configurable);
`route_after_tester` stops routing to Debugger once the limit is hit,
regardless of how many more times Tester reports failure — there is no
path to an infinite loop. Any agent's hard failure (LLM unavailable,
malformed output, unhandled exception) is caught by the node wrapper,
recorded as a failed `AgentStep`, and routed straight to `finalize` with
`execution_status="error"` — it never crashes the graph run silently.

## Agents implemented

| Agent | Tool permissions | Makes LLM calls |
|---|---|---|
| Orchestrator | none (routing/RAG-retrieval only) | no |
| Planner | read | yes |
| Developer | read, write | yes |
| Tester | read (execute once Phase 1.4 exists) | only if an execute tool is actually available |
| Debugger | read, write (implementation only reads) | yes |
| Reviewer | read | yes |

Permissions are enforced twice: the tool registry only *shows* an agent
tools within its granted set, and the tool-calling boundary
(`BoundToolRunner` in `backend/app/services/tool_execution.py`)
independently *rejects* any tool name outside that set before running it
— bypassing the first check by asking an LLM to name a disallowed tool
still fails the second.

Agent classes have no SQLAlchemy dependency at all — they only see a
`StructuredLLMClient` and a `ToolRunner` protocol (`agents/base.py`). DB
sessions, `AgentStep`/`ToolCall` persistence, and `BoundToolRunner`
construction all live in the graph node wrapper
(`agents.graph.make_agent_node`), keeping every agent independently unit
testable with fakes (`tests/fakes.py`) and free of any live LLM/DB
requirement in tests.

## RAG / indexing architecture

```
Repository → file discovery → filtering (exclude .git/node_modules/.venv/
  __pycache__/dist/build/coverage/binary/oversized) → line-based chunking
  (60 lines, 10-line overlap) → embedding → pgvector → cosine-similarity
  retrieval → deduplicated, size-bounded context
```

- `rag/exclusions.py` extends the same excluded-directory set the
  `search_files` tool uses, plus indexer-specific extras.
- `rag/chunking.py` — simple line-based chunking with overlap (no
  AST/tree-sitter parsing; a reasonable 24-hour-budget tradeoff).
- `rag/ingestion/indexer.py` (`RepositoryIndexer.index_repository`) —
  explicit indexing, not a file watcher. Re-indexing a file replaces its
  chunks (`replace_chunks_for_file`), which is idempotent and the seed of
  incremental indexing without hash-diffing complexity.
- `rag/retrieval/retriever.py` — embeds the query, runs a pgvector
  cosine-distance search scoped to one project, returns ranked
  `RetrievedChunk`s with file path, chunk index, score, and metadata.
- `rag/retrieval/context_builder.py` — deduplicates, enforces a character
  budget (`DEFAULT_MAX_CONTEXT_CHARS = 12000`), and formats chunks with
  file-path/chunk headers into the `RepositoryContext` agents consume.

## Embedding provider

Provider-agnostic, mirroring the LLM abstraction (`rag/embeddings/base.py`
+ `rag/embeddings/factory.py`, selected via `EMBEDDING_PROVIDER`):

- **`hashing`** (default): a free, local, deterministic feature-hashing
  bag-of-words embedding — zero dependencies, no download, no API key.
  It is **not** a learned semantic embedding; shared vocabulary between a
  query and a chunk increases similarity (verified in tests), but it has
  none of a real model's understanding of meaning or synonyms. This
  exists so the full pipeline is genuinely exercised without requiring a
  paid API to run the architecture at all.
- **`openai_compatible`**: any OpenAI-compatible embeddings endpoint
  (`EMBEDDING_BASE_URL`/`EMBEDDING_MODEL`/`EMBEDDING_API_KEY`), truncated
  to the fixed schema width via the `dimensions` parameter.

Swapping providers is a config change; no RAG code changes.

## pgvector schema

`repository_chunks` (Alembic revision `1767a56b96bc`): `project_id`,
`file_path`, `chunk_index`, `content`, `embedding` (`vector(384)`,
provider-agnostic fixed width), `metadata` (JSONB — `start_line`,
`end_line`, `language`), `created_at`, `updated_at`. Indexed on
`(project_id, file_path)` for the delete-and-replace re-indexing pattern.
No ANN index (ivfflat/hnsw) yet — full scans are correct and fast enough
at this scale; worth adding once real repositories are indexed at volume.

## Retrieval behavior

Pure cosine-similarity vector search today, scoped to one project,
configurable `top_k` (default 8). `RetrievedChunk` carries enough (file
path, chunk index, score) that a future hybrid lexical+semantic ranker
(merging in `search_files`-style keyword hits) can be added without
changing this return type — not built now, to avoid over-engineering
retrieval before there's a corpus large enough to need it.

## Execution API

`POST /api/v1/executions` accepts `{task, project_id | workspace_path (+
optional project_name)}`, creates the `Execution` record, and schedules
the graph run as a FastAPI background task — the HTTP response returns
immediately with the created record (`status="pending"`).
`GET /api/v1/executions/{id}` polls for status. Routes never touch agents
or the graph directly; both call
`backend.app.services.execution_service`, which owns the full run
lifecycle and DB session for the background task. There is no endpoint
that executes an arbitrary tool or command.

## Persistence integration

Every graph run writes real rows: an `AgentStep` per Planner/Developer/
Tester/Debugger/Reviewer invocation (agent name, status, start/end,
structured output summary, error message on failure), and a `ToolCall`
per real tool invocation those agents make (via the same Phase 1.2
`execute_tool` path, output truncated before storage). The Orchestrator's
init/finalize nodes update the `Execution` row's status directly. No
secrets or raw credentials are ever included in what gets persisted.

## Security measures

- **Prompt injection from repository content**: every agent whose prompt
  includes task/repository/diff/test-output text is explicitly instructed
  that this content is untrusted data, not instructions, and must never
  override the system prompt. This is a mitigation, not a guarantee — a
  sufficiently adversarial repository could still influence a real LLM's
  output text (e.g. a bad `Plan`), but it cannot escalate to unauthorized
  tool access, because permissions are enforced structurally (see below),
  not by the LLM choosing to behave.
- **Tool permission bypass**: enforced twice — registry filtering (what an
  agent is *shown*) and `BoundToolRunner` (what it's *allowed to call*,
  checked independently). Tested per agent (`tests/unit/agents/test_permissions.py`,
  plus explicit "never calls a write tool" tests for Planner/Debugger/Reviewer).
- **Unauthorized filesystem access**: unchanged from Phase 1.2 — every
  tool resolves paths through `Workspace.resolve()`.
- **Arbitrary command execution**: no tool with `Permission.EXECUTE` is
  registered anywhere in the Phase 1.3 tool registry; Tester detects this
  honestly rather than assuming or fabricating.
- **Unbounded retries**: `MAX_DEBUG_RETRIES` (default 2), enforced in
  `route_after_tester` and unit-tested directly, including "still failing
  well past the limit" cases.
- **Unbounded context**: RAG context capped at 12,000 characters;
  Developer's file pre-fetch capped at 8 files; `read_file` capped at 1MB
  (Phase 1.2); indexing skips files over 500KB and binary content.
- **Secret leakage**: LLM/embedding API keys are never logged or
  persisted; `.env` stays gitignored. Tool-call outputs are truncated
  before storage but not secret-scrubbed — see Known Limitations.

## Tests / results

177 tests passing, 1 skipped (the live Qwen smoke test — no API key in
this environment), verified against a freshly migrated database (full
`docker compose down -v` / `up` / `alembic upgrade head` cycle). No test
requires a live paid LLM API — every agent test injects
`FakeStructuredLLMClient`/`FakeToolRunner` (`tests/fakes.py`); the
production path always uses the real provider. Coverage includes: graph
construction and routing (retry limits, error short-circuiting), every
agent's structured output handling and malformed-output/LLM-unavailable
behavior, tool-permission enforcement, RAG chunking/exclusions/hashing-
embedding/context-building (unit) and indexing/retrieval/vector-CRUD
(integration, real Postgres), and the execution API end-to-end (real HTTP
request → real background task → real graph run → honest terminal
status).

## Technology stack

- Python, FastAPI, Pydantic / Pydantic Settings
- LangChain (LLM/embeddings integration), LangGraph (agent orchestration)
- PostgreSQL with pgvector, SQLAlchemy (async), Alembic
- Redis
- Docker / Docker Compose
- pytest

## Local setup

Requirements: Python 3.10+, Docker, Docker Compose, Git.

```bash
# 1. Create a venv and install dependencies
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# edit .env — LLM_API_KEY (for real agent runs), EMBEDDING_PROVIDER if
# you want real semantic embeddings instead of the free local default
```

Or run `scripts/setup/bootstrap.sh` to do both steps in one command.

### Start PostgreSQL and Redis

```bash
docker compose up -d
```

This starts:
- `postgres` — PostgreSQL with the `pgvector` extension enabled on startup
  (default host port **5433**, not 5432 — chosen to avoid clashing with a
  locally installed PostgreSQL, which is common on dev machines)
- `redis` — Redis with AOF persistence (default host port **6380**, not
  6379, for the same reason)

Both expose health checks (`docker compose ps` shows their status).

### Apply database migrations

```bash
alembic upgrade head
```

This creates the full application schema (`projects`, `executions`,
`agent_steps`, `tool_calls`, `artifacts`, `repository_chunks`) against the
PostgreSQL instance described by your `.env`. To reverse the most recent
migration: `alembic downgrade -1`.

### Start the API

```bash
uvicorn backend.app.main:app --reload
# or: scripts/development/run.sh
```

Then check:
- `GET http://localhost:8000/health` — liveness
- `GET http://localhost:8000/health/ready` — readiness (checks PostgreSQL + Redis)
- `GET http://localhost:8000/api/v1/tools` — registered tool schemas
- `POST http://localhost:8000/api/v1/executions` — `{"task": "...", "workspace_path": "/path/to/a/repo"}`
  to run the real agent pipeline against a real local repo/directory
- `GET http://localhost:8000/api/v1/executions/{id}` — poll for status

### Local/self-hosted Qwen compatibility

`LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` point at any OpenAI-compatible
chat-completions endpoint — a hosted Qwen3-Coder provider (DashScope,
OpenRouter, ...) or a local server (vLLM, Ollama's OpenAI-compatible
endpoint, etc.) both work identically; nothing in `agents/` or `backend`
references a specific vendor.

### Run tests

```bash
pytest
# or: scripts/development/test.sh
```

Database, Redis, and live-LLM tests skip gracefully (rather than fail)
when their dependency isn't reachable/configured. Agent and RAG unit tests
never touch a live LLM or Postgres at all.

## Environment configuration

All configuration is environment-variable driven (see `.env.example`):
application settings, PostgreSQL/Redis connection info, LLM
provider/base URL/model/API key, embedding provider/base URL/model/API
key/dimension, and `MAX_DEBUG_RETRIES`. Secrets are never committed —
`.env` is gitignored; only `.env.example` (placeholder values) is tracked.

## Project layout

```
backend/app/                    FastAPI application
backend/app/db/models/          SQLAlchemy models (incl. repository_chunk)
backend/app/db/repositories/    Persistence functions per model
backend/app/services/           execution_service (API<->graph boundary), tool_execution
agents/                         LangGraph state, graph, and the 5 LLM-driven agents
tools/                          Controlled tool system: workspace, contracts, registry
rag/                            Chunking, embeddings, indexing, retrieval, context building
database/migrations/            Alembic environment and migration scripts
execution/                      Docker sandbox + per-run workspaces (Phase 1.4)
infrastructure/                 Docker Compose service configuration
```

## Known limitations

- No Docker sandbox / real test-command execution yet — Tester honestly
  reports `status="unavailable"` (Phase 1.4).
- The default embedding provider is a hashing bag-of-words vector, not a
  learned semantic model — retrieval quality is keyword-driven, not
  meaning-driven, until `EMBEDDING_PROVIDER=openai_compatible` (or a
  future local-model provider) is configured.
- No ANN index on `repository_chunks.embedding` yet (full scan) — fine at
  current scale, worth revisiting once real repos are indexed at volume.
- Prompt-injection mitigation is instructional (explicit "untrusted data"
  framing in system prompts), not a hard technical guarantee against a
  determined adversarial repository.
- Tool-call outputs are size-truncated before persistence but not
  secret-scrubbed.
- No auth on the API — acceptable for a local single-user Phase 1 tool,
  not for anything exposed beyond localhost.
