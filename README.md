# LocoPilot

LocoPilot is an autonomous AI software engineering agent. It accepts a
software task and a repository, understands the codebase, plans an
implementation, modifies code through controlled tools, runs tests,
diagnoses and fixes failures, reviews the resulting diff, and returns a
structured engineering result.

## Status: Phase 1.1 — Foundation

This milestone establishes the project's foundation only. It does **not**
yet include the agent graph, RAG, or code execution. What's implemented:

- FastAPI application with liveness/readiness endpoints
- Centralized, environment-driven configuration
- Async PostgreSQL connectivity (pgvector extension enabled, ready for
  future embedding storage)
- Async Redis connectivity
- A provider-agnostic LLM abstraction, with Qwen3-Coder wired up through an
  OpenAI-compatible API
- Structured logging with execution-correlation hooks for future agent runs
- Docker Compose infrastructure for PostgreSQL and Redis
- A test suite covering configuration, health endpoints, DB/Redis
  connectivity, and LLM provider initialization

## Architecture

```
Client → FastAPI (backend/app/api)
           │
      Orchestrator (LangGraph, later milestone)
           │
   Repository Analyzer → RAG → Planner → Developer → Tester → Debugger → Reviewer
           │
   Controlled tools (filesystem, git, terminal) → Docker execution sandbox
```

Phase 1.1 provides the substrate everything above is built on: the API
process, its configuration, its connections to PostgreSQL/Redis, and the
LLM abstraction agents will call through. The `agents/`, `tools/`, and
`rag/` packages are scaffolded but intentionally empty until later
milestones.

The LLM layer is provider-agnostic by design:

```
LLM Interface (backend/app/core/llm/base.py)
    ↓
Qwen Provider (backend/app/core/llm/qwen_provider.py)
    ↓
OpenAI-compatible API (DashScope / OpenRouter / Together / ...)
```

Adding a new provider means implementing `LLMProvider` and registering it
in `backend/app/core/llm/factory.py` — no changes to any agent code.

## Technology stack

- Python, FastAPI, Pydantic / Pydantic Settings
- LangChain (LLM abstraction), LangGraph (planned — agent milestone)
- PostgreSQL with pgvector, SQLAlchemy (async)
- Redis
- Docker / Docker Compose
- pytest

## Local setup

Requirements: Python 3.10+, Docker, Docker Compose.

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
- `redis` — Redis with AOF persistence

Both expose health checks (`docker compose ps` shows their status).

### Start the API

```bash
uvicorn backend.app.main:app --reload
# or: scripts/development/run.sh
```

Then check:
- `GET http://localhost:8000/health` — liveness
- `GET http://localhost:8000/health/ready` — readiness (checks PostgreSQL + Redis)
- `GET http://localhost:8000/api/v1/` — versioned API root

### Run tests

```bash
pytest
# or: scripts/development/test.sh
```

Database, Redis, and live-LLM tests skip gracefully (rather than fail) when
their dependency isn't reachable/configured, so `pytest` is deterministic
even without Docker or an LLM API key present.

## Environment configuration

All configuration is environment-variable driven (see `.env.example`):
application settings, PostgreSQL connection info, Redis connection info,
and LLM provider/base URL/model/API key. Secrets are never committed —
`.env` is gitignored; only `.env.example` (placeholder values) is tracked.

## Project layout

```
backend/app/        FastAPI application (api, core config/logging/llm, db, services)
agents/              Agent implementations (later milestone)
tools/               Controlled tool interfaces (later milestone)
rag/                 Repository retrieval (later milestone)
execution/           Docker sandbox + per-run workspaces (later milestone)
infrastructure/      Docker Compose service configuration
database/            Migrations/seeds (later milestone)
```
