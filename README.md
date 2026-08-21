# LocoPilot

LocoPilot is an autonomous software-engineering agent. Give it a task and a
workspace (an existing project or a blank one it provisions for you), and it
plans an implementation, writes and edits code through a controlled tool
system, runs tests in an isolated sandbox, debugs failures, reviews its own
diff, and reports the result — with every step, tool call, and artifact
persisted and inspectable through a web dashboard.

## LocoPilot v1

This is the first complete, end-to-end milestone: a working agent pipeline,
a real API, a real dashboard, and a real (if intentionally bounded) local
coding-agent workflow. It is **not** production software — see
[Known limitations](#known-limitations) before relying on it for anything
beyond local, single-user use.

What v1 includes:

- A LangGraph pipeline (Orchestrator → Planner → Developer → Tester →
  Debugger ↺ → Reviewer) where Developer and Debugger are genuine
  tool-calling agents — the model itself chooses which tools to call, not a
  hand-scripted sequence.
- A controlled tool system (filesystem, git, terminal) where every call is
  permission-checked and path-resolved through a single sandbox boundary —
  no tool ever touches a path outside the authorized workspace.
- Retrieval over the target repository (pgvector-backed), re-retrieved at
  each stage against what that stage is actually doing, with incremental
  re-indexing after every file change.
- Real, isolated command/test execution in a locked-down Docker sandbox
  (non-root, read-only root filesystem, all capabilities dropped, no
  network by default, resource-limited) — never on the host.
- Bounded autonomy: per-agent and execution-wide tool-call budgets, a
  wall-clock execution timeout, and a bounded debug-retry loop, so a
  misbehaving model can't run away with the process.
- Full execution/audit persistence (executions, agent steps, tool calls,
  artifacts) and a read API over it, with secrets scrubbed before anything
  is written to the database.
- A Next.js dashboard: a landing command composer, a workspace command
  center (attachments, voice input, workspace selection), live execution
  polling, an agent-pipeline view, a tool-call inspector, a reconstructed
  diff view, test results, and system/LLM status — no fabricated data;
  genuine empty states where there's nothing to show yet.
- A provider-agnostic LLM layer: **Gemini is the default provider**; Qwen
  (or any OpenAI-compatible endpoint) remains fully supported and is a
  configuration change, not a code change.

## Architecture

```
Next.js dashboard  ──HTTP──>  FastAPI (backend/app)
                                  │
                        execution_service (create/run/cancel)
                                  │
                            LangGraph (agents/graph.py)
                                  │
   Orchestrator ─▶ Planner ─▶ Developer ─▶ Tester ─▶ Debugger ─▶ Reviewer
                                  │             │         │
                                  ▼             ▼         ▼
                          Tool Registry   Docker Sandbox  RAG (pgvector)
                       (filesystem/git/terminal, permission-checked)
                                  │
                         PostgreSQL (executions, steps, tool calls,
                                     artifacts, repository_chunks)
                                  │
                               Redis (cache / pub-sub scaffolding)
```

- **Agents** (`agents/`): shared `AgentState`, a `BaseAgent`, and the five
  pipeline agents. Developer/Debugger use a bounded tool-calling loop
  (`agents/llm_client.py`); every agent turn persists an `AgentStep`.
- **Tools** (`tools/`): filesystem, git, and terminal tools, each declared
  with a Pydantic input/output schema and a required `Permission`. Every
  path is resolved through `tools/workspace.py`'s `Workspace`, which rejects
  absolute paths, `../` traversal, and symlink escapes — the single
  boundary every tool, and the dashboard's file-browsing/upload endpoints,
  rely on.
- **Sandbox** (`execution/docker/`): one Docker container per
  `execute_terminal_command` call, driven via the `docker` CLI (never the
  Docker SDK, never a shell string) — non-root, read-only root filesystem,
  all capabilities dropped, resource-limited, network disabled unless a
  policy explicitly allows it, destroyed in a `finally` block regardless of
  outcome.
- **RAG** (`rag/`): chunking, a pluggable embeddings provider (a free local
  hashing embedder by default; any OpenAI-compatible embeddings endpoint
  optionally), pgvector storage, and stage-specific retrieval.
- **Persistence** (`backend/app/db/`): SQLAlchemy async models + Alembic
  migrations for projects, executions, agent steps, tool calls, and
  artifacts. Secrets are scrubbed (`backend/app/security/secret_scrubber.py`)
  before any tool-call output or agent-step metadata is written.
- **Workspace storage**: projects live at an explicit `workspace_path`. If
  none is given, LocoPilot provisions one automatically under a configurable
  `LOCOPILOT_WORKSPACE_ROOT` (default: a platform-appropriate application-data
  directory — never a path inside the repository, never a hardcoded personal
  path), structured as `projects/`, `uploads/`, `executions/`, `artifacts/`.
- **Frontend** (`frontend/`): Next.js (App Router) + TypeScript + Tailwind,
  polling the read API for live updates (no WebSocket/SSE — deliberately the
  simplest reliable mechanism for this scale).

## LLM provider

Provider-agnostic by design (`backend/app/core/llm/`): agents and tools
depend only on `StructuredLLMClient` / `LLMProvider`, never on a concrete
vendor. Selecting a provider is a `.env` change:

```
LLM_PROVIDER=gemini            # gemini (default) | qwen
LLM_API_KEY=...
LLM_MODEL=gemini-pro-latest    # or qwen3-coder-plus, etc.
LLM_BASE_URL=                  # only required for OpenAI-compatible providers (e.g. qwen)
```

- **Gemini** (`backend/app/core/llm/gemini_provider.py`) talks to Google's
  Generative Language API directly via `langchain-google-genai`.
- **Qwen** (`backend/app/core/llm/qwen_provider.py`) talks to any
  OpenAI-compatible chat-completions endpoint (DashScope, OpenRouter, a
  local vLLM/Ollama server, ...) via `langchain-openai`.

Adding a third provider means registering it in
`backend/app/core/llm/factory.py`, not touching any agent.

The Settings page (and `GET /health/llm`) reports real, live LLM status —
distinguishing **not configured**, **authentication failed**, and **model
access denied** (a valid key without an activated/purchased model, which is
a provider-account issue, not a LocoPilot bug) from **connected** — without
ever exposing the API key.

## Technology stack

- Python, FastAPI, Pydantic / Pydantic Settings
- LangChain + LangGraph (orchestration), `langchain-google-genai` /
  `langchain-openai` (providers)
- PostgreSQL with pgvector, SQLAlchemy (async), Alembic
- Redis
- Docker / Docker Compose (Postgres + Redis) + the `docker` CLI (sandbox)
- Next.js, TypeScript, Tailwind CSS, TanStack Query
- pytest, Vitest

## Getting started

Requirements: Python 3.10+, Node.js 20+, Docker, Docker Compose, Git.

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
- `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` — see [LLM provider](#llm-provider) above.
- `LOCOPILOT_WORKSPACE_ROOT` — optional; leave unset to use the platform default.
- Everything else (Postgres/Redis ports, resource limits, CORS) has a
  working local default.

`frontend/.env.local` needs `NEXT_PUBLIC_API_BASE_URL` (see
`frontend/.env.example`) — defaults to `http://localhost:8000`.

### 2. Start PostgreSQL and Redis

```bash
docker compose up -d
```

### 3. Build the sandbox image (once)

```bash
docker build -t locopilot-sandbox-python:1.0 -f execution/docker/Dockerfile execution/docker
```

Without this, Tester's real execution path and the Docker-backed test suite
skip gracefully with a clear message rather than failing.

### 4. Install dependencies and apply migrations

```bash
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
alembic upgrade head
```

### 5. Start the backend

```bash
uvicorn backend.app.main:app --reload
```

- `GET /health` — liveness
- `GET /health/ready` — Postgres + Redis
- `GET /health/llm` — LLM provider status (never exposes the key)
- `POST /api/v1/executions` — `{"task": "..."}` to run against an
  auto-provisioned workspace, or add `project_id` / `workspace_path` to
  target an existing one

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

### Run tests

```bash
pytest                 # backend — Postgres/Redis/Docker/live-LLM dependent
                        # tests skip gracefully (never fail) when unavailable
cd frontend && npm run test   # frontend
```

## Project layout

```
backend/app/                FastAPI app: API routes, db models/repositories, services, LLM providers
agents/                     LangGraph state, graph, and the five pipeline agents
tools/                      Controlled tool system: workspace boundary, filesystem/git/terminal tools
rag/                        Chunking, embeddings, pgvector storage, retrieval
execution/docker/           Sandbox implementation, Dockerfile, network/resource policy
database/migrations/        Alembic environment and migrations
frontend/                   Next.js dashboard (App Router, TypeScript, Tailwind)
playground/                 Deterministic fixture projects used by integration tests
infrastructure/             Docker Compose service configuration (Postgres/Redis)
```

## Known limitations

- **No authentication** — acceptable for a local, single-user tool; not for
  anything exposed beyond localhost.
- **Cancellation** is checked between agent turns, not mid-tool-call, and is
  in-process (not distributed) — correct for today's single-worker
  background-task model.
- **Workspace file browsing** is API-only today (`GET
  /api/v1/projects/{id}/files`, upload endpoint); the dashboard does not yet
  have a visual directory-tree picker — a file is referenced by typing its
  workspace-relative path in the task description.
- **"Local folder" workspace selection** is a validated path input, not a
  browser folder picker — browsers cannot reveal a real OS path from a
  picker dialog, so the backend (which already runs on the same machine as
  your files) resolves the path you provide directly, through the same
  sandbox boundary every tool uses.
- **Embeddings default to a free local hashing vector**, not a learned
  semantic model — swappable via `EMBEDDING_PROVIDER`.
- **Prompt-injection mitigation is instructional, not a hard guarantee** —
  tool permission enforcement remains structural regardless (a tool call
  outside an agent's granted permissions is rejected independent of what
  the model requests).
- **Secret scrubbing is pattern-based defense-in-depth**, not exhaustive
  detection.
- Container resource limits rely on Docker Desktop's Linux VM on Windows/
  macOS; exact cgroup behavior may differ on a bare-Linux Docker host.
