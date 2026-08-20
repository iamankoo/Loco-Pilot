# LocoPilot

LocoPilot is an autonomous AI software engineering agent. It accepts a
software task and a repository, understands the codebase, plans an
implementation, modifies code through controlled tools, runs tests,
diagnoses and fixes failures, reviews the resulting diff, and returns a
structured engineering result.

## Status: Phase 1.2 — Persistence + Controlled Tool System

Phase 1.1 (FastAPI/config/DB/Redis/LLM foundation) is done. This milestone
adds the application's persistence layer and the controlled tool system
future agents will call through. It does **not** yet include LangGraph
orchestration, the agent roles themselves, RAG, or Docker sandboxed
execution.

What's implemented:

- SQLAlchemy models (`Project`, `Execution`, `AgentStep`, `ToolCall`,
  `Artifact`) with an Alembic migration, applied against PostgreSQL
- Repository functions for creating/updating each of the above
- A workspace abstraction (`tools/workspace.py`) that every tool resolves
  paths through — the single boundary preventing path traversal,
  absolute-path escapes, and symlink escapes
- Real, tested filesystem tools: `list_directory`, `read_file`,
  `write_file`, `edit_file` (deterministic unique-match replace),
  `search_files`
- Real, tested Git tools: `git_status`, `git_diff`, `git_branch`,
  `git_create_branch` — each a fixed operation with its own argv, so there
  is no path to command injection or destructive commands
  (`reset --hard`, `clean -fd`, force-push) through this layer
- A typed terminal execution *contract* (`TerminalCommandRequest` /
  `TerminalCommandResult` / `ExecutionPolicy`) plus an internal-only local
  executor used by tests — not exposed to agents; Phase 1.3's Docker
  sandbox implements the same contract for real agent use
- A tool registry with permission-based filtering (`READ_ONLY`,
  `DEVELOPER`, ...), so a future agent can be handed only the tools it's
  allowed to use
- A tool-execution service bridging tool calls to persistence
  (`Execution` → `AgentStep` → `ToolCall`), with large outputs truncated
  before storage
- A read-only `GET /api/v1/tools` endpoint listing registered tool schemas
  (no execution exposed over HTTP)

## Architecture

```
Client → FastAPI (backend/app/api)
           │
      Orchestrator (LangGraph, later milestone)
           │
   Repository Analyzer → RAG → Planner → Developer → Tester → Debugger → Reviewer
           │
           ▼
   Agent → Tool Call → Tool Registry → Validation → Permission Boundary
           → Tool Implementation → Result → Execution/ToolCall persistence
```

Agents never touch the OS directly. Every capability an agent needs is
requested through a tool obtained from the registry, scoped to a
`ToolContext` bound to one `Workspace`. Filesystem/Git tools implement this
today; the terminal contract is defined but only reachable through Phase
1.3's Docker sandbox once that exists.

The LLM layer remains provider-agnostic (unchanged from Phase 1.1):

```
LLM Interface (backend/app/core/llm/base.py)
    ↓
Qwen Provider (backend/app/core/llm/qwen_provider.py)
    ↓
OpenAI-compatible API (DashScope / OpenRouter / Together / ...)
```

## Technology stack

- Python, FastAPI, Pydantic / Pydantic Settings
- LangChain (LLM abstraction), LangGraph (planned — agent milestone)
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
# edit .env — at minimum set LLM_API_KEY if you want the LLM smoke test to run
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

This creates the application schema (`projects`, `executions`,
`agent_steps`, `tool_calls`, `artifacts`) against the PostgreSQL instance
described by your `.env`. To reverse the most recent migration:

```bash
alembic downgrade -1
```

### Start the API

```bash
uvicorn backend.app.main:app --reload
# or: scripts/development/run.sh
```

Then check:
- `GET http://localhost:8000/health` — liveness
- `GET http://localhost:8000/health/ready` — readiness (checks PostgreSQL + Redis)
- `GET http://localhost:8000/api/v1/` — versioned API root
- `GET http://localhost:8000/api/v1/tools` — registered tool schemas (read-only; no execution endpoint)

### Run tests

```bash
pytest
# or: scripts/development/test.sh
```

Database, Redis, and live-LLM tests skip gracefully (rather than fail) when
their dependency isn't reachable/configured, so `pytest` is deterministic
even without Docker or an LLM API key present. The tool-system tests
(`tests/unit/tools`) don't touch Postgres/Redis at all — they run against
temporary directories and a temporary Git repo created per test.

## Environment configuration

All configuration is environment-variable driven (see `.env.example`):
application settings, PostgreSQL connection info, Redis connection info,
and LLM provider/base URL/model/API key. Secrets are never committed —
`.env` is gitignored; only `.env.example` (placeholder values) is tracked.
Alembic reads the same settings at runtime (`database/migrations/env.py`),
so the database URL is never duplicated into a tracked config file.

## Project layout

```
backend/app/           FastAPI application (api, core config/logging/llm, db, services)
backend/app/db/models/         SQLAlchemy models
backend/app/db/repositories/   Persistence functions per model
backend/app/services/          Cross-cutting services (tool execution -> persistence)
tools/                  Controlled tool system: workspace, contracts, registry
tools/filesystem/       list_directory, read_file, write_file, edit_file, search_files
tools/git/              git_status, git_diff, git_branch, git_create_branch
tools/terminal/         Typed execution contract + internal-only local executor
database/migrations/    Alembic environment and migration scripts
agents/                 Agent implementations (later milestone)
rag/                    Repository retrieval (later milestone)
execution/              Docker sandbox + per-run workspaces (later milestone)
infrastructure/         Docker Compose service configuration
```
