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
  wall-clock execution timeout, a bounded debug-retry loop
  (`MAX_DEBUG_RETRIES`), and an outer `MAX_AGENT_TURNS` cap on LangGraph's
  own recursion limit beneath it, so a misbehaving model can't run away
  with the process. Every graph transition is decided by explicit,
  independently-testable routing functions — never by the LLM itself — and
  a run is only ever reported "passed" if a real test run actually passed,
  regardless of what the Reviewer's own verdict says.
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
        │                         │             │         │
        ▼                         ▼             ▼         ▼
   analysis/ (workspace     Tool Registry   Docker Sandbox  RAG (pgvector)
   intelligence, once)   (filesystem/git/terminal, permission-checked)
                                  │
                         PostgreSQL (executions, steps, tool calls,
                                     artifacts, repository_chunks)
                                  │
                               Redis (cache / pub-sub scaffolding)
```

- **Agents** (`agents/`): shared `AgentState`, a `BaseAgent`, and the five
  pipeline agents. Developer/Debugger use a bounded tool-calling loop
  (`agents/llm_client.py`); every agent turn persists an `AgentStep`.
- **Workspace intelligence** (`analysis/`): before Planner ever runs, the
  Orchestrator builds a deterministic `ProjectContext` — a bounded,
  structured repository scan (directories/files/tests/config, excluding
  `.git`/`node_modules`/`.venv`/build output, capped file count and depth),
  language/framework/test-framework detection from real dependency-manifest
  evidence (never a filename guess), parsed dependency summaries, git
  awareness (branch/status), and task-relevant file discovery combining
  filename/keyword matching with RAG retrieval. None of it is LLM-driven;
  Planner only ever interprets the result. A failure in any one stage is
  recorded as a warning and the run continues with an explicitly
  `incomplete` context rather than fabricating an understanding.
- **Workspace discovery** (`backend/app/services/workspace_discovery.py`):
  resolves which project an execution targets — an explicit `project_id`/
  `workspace_path` is used as-is; a `project_name` (or a name mentioned in
  the task, e.g. "...in DeepLens") is matched against existing projects
  first; only a task that clearly asks to create something ("Create a C++
  calculator") provisions a brand-new workspace when no match exists — a
  read/fix/check task naming a project that doesn't exist honestly reports
  "not found" instead of silently creating an empty directory.
- **Tools** (`tools/`): filesystem (`list_directory`, `read_file`,
  `write_file`, `edit_file`, `delete_file`, `move_file`, `file_exists`,
  `search_files`), git, and terminal tools, each declared with a Pydantic
  input/output schema and a required `Permission`. Every path is resolved
  through `tools/workspace.py`'s `Workspace`, which rejects absolute paths,
  `../` traversal, and symlink escapes — the single boundary every tool,
  and the dashboard's file-browsing/upload endpoints, rely on. Every
  mutating call (`write_file`/`edit_file`/`delete_file`) verifies the
  filesystem actually reflects the change before reporting success and
  returns a bounded unified diff (`tools/diffing.py`); `delete_file`
  refuses to remove a non-empty directory without `recursive=True` or the
  workspace root under any circumstances, and `move_file` never silently
  overwrites an existing file or directory. Only Developer holds `WRITE`
  (Planner/Tester/Reviewer are read-only, and Debugger — though granted
  `WRITE` at the permission-table level for interface completeness — is
  restricted to a read-only tool allowlist at the graph level, so it only
  ever diagnoses, never mutates).
- **Sandbox** (`execution/docker/`): one Docker container per
  `execute_terminal_command` call, driven via the `docker` CLI (never the
  Docker SDK, never a shell string) — non-root, read-only root filesystem,
  all capabilities dropped, resource-limited, network disabled unless a
  policy explicitly allows it, destroyed in a `finally` block regardless of
  outcome.
- **RAG** (`rag/`): repository -> chunking -> embedding -> pgvector ->
  hybrid retrieval -> bounded context assembly, feeding Planner/Developer/
  Debugger. See [RAG architecture](#rag-architecture) below.
- **Tester** (`agents/tester.py`): reuses the Orchestrator's own
  `ProjectContext` for framework detection (never re-scans the workspace
  itself) and prefers a targeted test selection
  (`analysis/test_selection.py` — the changed files' own directory/name
  plus the task's keywords) over the whole suite, falling back to the
  detected test directory and then the bare framework command only when
  nothing more specific matches. Status, pass/fail/skipped counts, and
  failing test names are always parsed deterministically from the real
  exit code and output of the actual command that ran inside the Docker
  sandbox — never from an LLM's reading of the output.
- **Debugger** (`agents/debugger.py`): classifies the real `TestResult`
  into a `failure_class` (syntax/import/dependency/assertion/type/build/
  environment/timeout/... error) via `agents/failure_classification.py`
  — a deterministic regex match over the real output, never an LLM
  guess — before investigating. Every prior attempt in the current retry
  cycle (`state.debug_attempts`) is shown in its prompt so it doesn't
  repeat an already-unsuccessful strategy; Tester patches each attempt's
  outcome to "fixed"/"unresolved" once the fix is actually re-tested,
  since that's only knowable after Debugger's own turn ends.
  `MAX_DEBUG_RETRIES` remains the sole termination authority (unchanged
  from Phase 2.1) — attempt history is additional context and
  observability, not a second loop-control mechanism.
- **Reviewer** (`agents/reviewer.py`): an independent gate, not a rubber
  stamp — reads the real git diff, the real `files_changed`, real test
  results, and the debug-attempt history, and detects several things
  deterministically before the LLM ever weighs in: files changed outside
  the plan's own stated scope, a deleted test file, and a diff pattern
  that looks like a real assertion was replaced with a trivial
  `assert True`. Any of these forces a `risk` floor ("medium"/"high")
  that an LLM's own (lower) assessment can never undercut — `risk` is the
  max of the two, never just the model's guess. A "changes_required"
  verdict now genuinely routes back to Developer -> Tester -> Reviewer,
  bounded by its own `MAX_REVIEW_RETRIES` counter (independent of the
  debug loop's). Whether an execution can honestly be reported "passed" —
  an approved review is necessary but never sufficient without a real
  passing test result — is decided by one function,
  `agents.state.compute_honest_status`, used identically by the graph's
  own finalize node and the service layer's DB-status mapping, so the
  two can never disagree with each other.
- **Git awareness**: a workspace is never assumed to start clean — the
  Orchestrator's `ProjectContext` captures the real branch/status *before*
  any agent runs, and `state.files_changed` (populated only from
  Developer's own real tool calls) is the authoritative record of what this
  execution actually did. `git_diff` accepts a `paths` scope
  (`tools/git/tools.py`); the Reviewer always scopes it to exactly
  `files_changed`'s own paths, so a diff it reviews can never include the
  user's own pre-existing uncommitted work. Branch creation/checkout is
  wired but ungranted to any agent (`GIT_WRITE` is outside
  `DEVELOPER_PERMISSIONS`), and `git_commit` remains, as in Phase 1.2,
  unregistered as an agent-callable tool — LocoPilot never commits or
  pushes on its own. `agents/commit_summary.py` generates a
  conventional-commit-style message from real persisted state (files
  changed, test/review outcome) for a human to use when they choose to
  commit — it never executes a commit itself.
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

## RAG architecture

```
Repository -> Discovery -> Chunking -> Embedding -> pgvector
           -> Hybrid retrieval -> Context assembly -> Planner / Developer / Debugger
```

**Why RAG at all, and why not send the whole repository to the model:**
software repositories are too large and change too often to reliably fit
entirely into a model's context window, and even when a repository is
small enough, most of it is irrelevant to any one task. RAG (retrieval
over embedded chunks) narrows the repository down to a bounded, relevant
slice before the model ever sees it.

**Why RAG *and* deterministic repository analysis (`analysis/`), not RAG
alone:** semantic retrieval can miss evidence pure similarity search isn't
built to catch — an explicitly-named file ("check config.py"), a project's
actual detected language/framework, or a test directory identified by
naming convention. Deterministic signals give retrieval something
dependable to lean on regardless of embedding quality, and RAG in turn
covers cases deterministic rules can't (loosely related code with no
name/path overlap). Neither replaces the other.

**Chunking** (`rag/chunking.py`): line-based with overlap (60 lines,
10-line overlap by default) — deliberately not a per-language AST/parser.
A real parser for Python/JS/TS/Java/C/C++/Go/Rust/Dart would be a much
larger dependency and maintenance surface for a benefit line-based
chunking with generous overlap mostly already captures (a function rarely
spans more than a couple of chunks, and the overlap keeps its signature
and body together in at least one chunk). What Phase 2.4 adds instead is
lightweight, regex-based **symbol extraction** (`rag/symbols.py`) per
chunk — bounded, best-effort function/class names, not a claim of correct
parsing — used only as a retrieval signal, not to change chunk boundaries.

**Embeddings** (`rag/embeddings/`): provider-agnostic. The default
`HashingEmbeddingProvider` is a free, local, deterministic hash
projection — intentionally not a real semantic model, so RAG works with
no API key and no live-API dependency in tests. An `OpenAICompatibleEmbeddingProvider`
is available for a real semantic embedding endpoint via configuration
only (`EMBEDDING_PROVIDER=openai_compatible`); retrieval/ranking logic
does not change based on which provider is active.

**Hybrid retrieval** (`rag/retrieval/hybrid.py`): because the default
embedding provider's cosine similarity is a weak signal on its own, a wide
semantic candidate pool (pgvector, project-scoped) is re-ranked using
deterministic signals — filename/path keyword matches, content keyword
hits, symbol matches (a stronger, separately-weighted bonus when the task
names a compound identifier verbatim, e.g. "fix `authenticate_user`"), a
boost for an already-relevant test file, and a strong boost for a file the
task names explicitly (looked up directly if it isn't even in the
semantic candidate pool). This keeps a single retrieval system — hybrid
scoring re-ranks and augments the same pgvector-backed candidate pool
rather than adding a second index or search engine.

**Query construction** (`rag/retrieval/query_builder.py`): each agent
stage retrieves against a different, deliberately small slice of
execution state — Planner/Orchestrator against the task (plus any file
named explicitly or flagged by `analysis.relevant_files`), Developer
against the task, plan, and files it's about to touch, Debugger against
the actual test failure/traceback and the files Developer just changed —
never the entire accumulated state.

**Context assembly** (`rag/retrieval/context_builder.py`): deduplicated,
capped at a configurable character budget and a per-file chunk cap (so one
file can't dominate the budget), grouped under one `[FILE N] path` label
per file with a `lines A-B` sub-header per chunk rather than repeating the
full header for every chunk. Retrieved content is always labeled
`UNTRUSTED REPOSITORY CONTEXT` in every agent prompt — it is data an agent
reads, never an instruction it follows.

**Project isolation**: every retrieval query — semantic search and the
explicit-filename lookup alike — filters by `project_id` first; there is
no code path that queries `repository_chunks` without it.

**Incremental indexing** (`rag/ingestion/indexer.py`, wired from
`agents/graph.py`): a changed file is reindexed; a deleted file has its
chunks cleared (re-indexing a path that no longer exists on disk clears
its stale chunks); a renamed file has *both* its old path's chunks
cleared and its new path indexed (via `FileChange.source_path` — this
was a known Phase 2.3 limitation, fixed in Phase 2.4); an unchanged file
is never re-embedded.

**Current limitations**: the hashing embedding provider has no real
semantic understanding — hybrid scoring's deterministic signals are what
make retrieval useful today, not the embedding itself. Symbol extraction
is regex-based, not a real parser, and can miss unusual syntax. A future
local or hosted semantic embedding provider would slot in via
`EMBEDDING_PROVIDER` with no change to retrieval/ranking code.

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
