# LocoPilot

LocoPilot is an autonomous AI software engineering agent. It accepts a
software task and a repository, understands the codebase, plans an
implementation, modifies code through controlled tools, runs tests,
diagnoses and fixes failures, reviews the resulting diff, and returns a
structured engineering result. It is not a chatbot — there is no
conversational interface; the unit of interaction is a task submitted to
an execution.

## Status: Phase 1.5 — Autonomous Coding Loop + Real Qwen Validation

Phases 1.1 (foundation), 1.2 (persistence + controlled tools), 1.3
(LangGraph agents + RAG), and 1.4 (Docker sandbox) are done. This
milestone turns Developer and Debugger into genuine tool-calling agents —
the model itself decides which registry tools to call and in what order,
rather than the agent applying a separately-listed decision — and adds
the bounded-autonomy machinery (per-agent and execution-wide tool-call
budgets, a wall-clock execution timeout, cancellation) that makes running
that loop safe. It also wires incremental re-indexing, stage-specific RAG
retrieval, and artifact collection into the graph, and adds a second
deterministic fixture (a feature-addition task, not just a bug fix). It
does **not** yet include a professional dashboard, autonomous project
creation, or multi-user features — see Known Limitations.

What's implemented:

- A real, bounded LLM tool-calling loop (`agents/llm_client.py`'s
  `generate_with_tools`): the model requests tools via `bind_tools`,
  each request is executed through the same permission-checked
  `BoundToolRunner` every other tool call goes through, results are fed
  back as `ToolMessage`s, and the loop repeats until the model stops
  requesting tools — bounded by a per-agent tool-call limit
- Developer rebuilt on this loop: it reads, searches, writes, and edits
  through real tool calls the model itself chooses; `DeveloperPlan` is now
  just its closing summary, not a separate listed set of edits the agent
  applies afterward
- Debugger rebuilt on the same loop, scoped to read-only tools
  (`read_file`/`search_files`/`list_directory`/`git_status`/`git_diff`)
  even though its permission-table grant includes `WRITE` — this
  implementation only ever investigates
- Bounded self-correction: `MAX_TOOL_CALLS_PER_AGENT`,
  `MAX_TOTAL_TOOL_CALLS` (an execution-wide budget, not just per turn),
  `MAX_EXECUTION_SECONDS` (wraps the whole graph run), and
  `MAX_CONTEXT_CHARS` — all environment-configurable, all enforced, all
  tested to actually stop work rather than merely existing as unused
  settings
- A first cancellation mechanism (`POST /api/v1/executions/{id}/cancel`),
  checked between agent turns
- Stage-specific RAG re-retrieval: Developer retrieves against the task +
  plan it's about to implement, Debugger against the task + the actual
  failure it's diagnosing — not just Orchestrator's one initial
  task-based retrieval reused everywhere
- Incremental re-indexing: a file Developer successfully changes is
  re-chunked and re-embedded immediately, not left stale until a full
  repository re-index
- Artifact collection wired end to end: a `Plan.expected_artifact_glob`,
  if the Planner sets one, is matched against the workspace after a
  passed execution and recorded as real `Artifact` rows
- A second deterministic fixture (`playground/feature-project`) proving
  the feature-task path (no bug, no debug loop) alongside the existing
  bug-fix fixture
- Expanded live-Qwen validation (`backend/tests/test_llm_smoke.py`,
  `tests/integration/execution/test_live_qwen_e2e.py`) — skip-gated,
  never fabricated, covering structured output, tool-calling, grounded
  context understanding, plan production, and a full live graph run

## Sandbox architecture

```
Agent -> Tool Registry -> Permission Check -> execute_terminal_command
       -> DockerTerminalExecutor -> Sandbox -> docker CLI -> Command -> Result
       -> ToolCall persistence (scrubbed) -> Agent state
```

`Sandbox` (`execution/docker/sandbox.py`) is the only code that talks to
Docker, via the `docker` CLI through `asyncio.create_subprocess_exec` —
the same pattern already used for Git in `tools/git/tools.py`; never a
shell, never the `docker` Python SDK. Agents never import
`execution.docker` — they only ever see `execute_terminal_command`
through the registry, identically to every other tool.

**Container lifecycle**: one container per `execute_terminal_command`
call. `DockerTerminalExecutor.run()` always calls `sandbox.destroy()` in a
`finally` block — on success, on command failure, and on timeout —
verified by tests that check no container is left behind in any of those
three cases (`tests/integration/execution/test_docker_terminal_executor.py`).
The container itself runs `sleep infinity` as its entrypoint and is
driven entirely via `docker exec`, so multiple commands could reuse one
`Sandbox` instance if a future caller needed that (Tester currently
creates one per Tester turn).

**Workspace isolation**: exactly one bind mount — the execution's
workspace directory to `/workspace`, read-write. No other host path is
ever mounted (verified via `docker inspect` in tests, not just by reading
the source). `cwd` for a command is resolved through the same
`Workspace.resolve()` boundary every other tool uses before being turned
into a container path, so a `cwd` of `../../etc` or `/etc` is rejected
before `docker exec` ever runs — closing the same escape class a raw `-w`
flag would otherwise permit (the kernel resolves `..` in a working
directory argument regardless of no shell being involved).

## Container security

Every sandbox container, unconditionally:

| Control | Mechanism | Verified |
|---|---|---|
| Non-root | `--user 1000:1000` (image has a matching `sandbox` user) | `id -u` inside the container returns `1000` |
| Read-only root filesystem | `--read-only` + a writable `/tmp` tmpfs | writing outside `/workspace`/`/tmp` fails with a real OS error |
| No privilege escalation | `--security-opt no-new-privileges` | `docker inspect` |
| All capabilities dropped | `--cap-drop ALL` | `docker inspect` shows `CapDrop: ["ALL"]` |
| Never privileged | `--privileged` is never passed | `docker inspect` shows `Privileged: false` |
| Memory limit | `--memory` (default 512m) | `docker inspect` |
| CPU limit | `--cpus` (default 1.0) | `docker inspect` |
| Process limit | `--pids-limit` (default 128) | `docker inspect` |
| Network disabled by default | `--network none` | `NetworkMode: "none"`, plus a real blocked-connection attempt |
| No host env leakage | only explicitly-passed `-e` flags reach the container | a host env var set via the test process does not appear inside the container unless explicitly forwarded |
| Only the workspace is mounted | a single `-v` flag, nothing else | `docker inspect` shows exactly one bind mount |

Everything in that table has a corresponding test in
`tests/integration/execution/test_sandbox_security.py`, run against a real
container on this project's actual Docker Desktop installation — not
assumed compatible.

**What is not isolated**: the sandbox shares the host's Docker daemon and
kernel (this is standard container isolation, not a hypervisor/VM
boundary) — it is not a defense against a kernel-level container
escape. CPU/memory limits are enforced by the Linux cgroup controller
Docker Desktop's VM provides; behavior may differ slightly on a bare-Linux
Docker host. The read-only root filesystem does not protect `/workspace`
itself — that directory is intentionally writable, since that's where the
project being tested/built lives.

## Network policy

`execution/docker/policy.py` defines `NetworkPolicy`: `DISABLED` (default,
`--network none`), `ALLOWED` (the container's normal default network —
implemented, for a future case where a build genuinely needs package-
registry access), and `RESTRICTED` (reserved for an egress-allowlist
policy; raises `NotImplementedError` today rather than pretending to
enforce something that isn't built). `DockerTerminalExecutor` always
requests `DISABLED` unless the caller's `ExecutionPolicy.allow_network` is
explicitly set.

## Resource limits

`execution/docker/policy.py`'s `ResourceLimits`: `memory` (512m default),
`cpus` (1.0 default), `pids_limit` (128 default), `timeout_seconds` (60
default), `max_output_bytes` (500,000 default). `DockerTerminalExecutor`
takes the *minimum* of the caller's `TerminalCommandRequest` values and
the configured `ExecutionPolicy` ceiling, so a tool caller can request a
shorter timeout but never a longer one than policy allows. Timeout is
enforced at the command layer (`asyncio.wait_for` around `docker exec`,
with a `docker kill` on expiry — a timed-out `docker exec` client
returning does not stop the process still running inside the container's
own namespace, so the container itself is what actually gets killed) and
independently by the Docker daemon's own resource accounting
(memory/pids/cpu limits apply regardless of what the command does).

## Terminal implementation

`DockerTerminalExecutor` (`tools/terminal/docker_executor.py`) implements
the exact same `TerminalCommandRequest -> TerminalCommandResult` contract
Phase 1.2 defined. Commands are always argv (`["python", "-m", "pytest"]`,
`["npm", "test"]`, ...), never a shell string — there is no `shell=True`
anywhere in this codebase, and no caller-supplied string is ever
interpolated into one. `TerminalCommandResult` reports `status` (via
`exit_code`), `stdout`/`stderr` (byte-capped, with `*_truncated` flags),
`duration_ms`, and `timed_out` — a timeout never gets reported as success,
and a nonzero exit code is never silently treated as passing.

## Execute tool

`execute_terminal_command` (`tools/terminal/tools.py`) is the only
`Permission.EXECUTE` tool in the registry. It is reached exactly as every
other tool is: `Agent -> BoundToolRunner -> permission check -> Tool.run()`
— there is no path from an agent directly to Docker. A `SandboxError`
(Docker unavailable, image missing, container creation/start failure) is
caught and converted into a `ToolError`, so a Docker-level failure becomes
a structured tool failure, not a crash.

## Tester integration

Tester (`agents/tester.py`) is unchanged in structure from Phase 1.3 — it
still checks its own actually-permitted tool names before assuming
execution is possible. What changed: `TESTER_PERMISSIONS` now includes
`Permission.EXECUTE`, so the tool is genuinely available, and Tester now:

1. Detects an appropriate command from real project marker files
   (`pyproject.toml`/`pytest.ini`/`setup.py` → `python -m pytest`,
   `package.json` → `npm test`, `build.gradle(.kts)` → `./gradlew test`) —
   never fabricates a command; reports `status="unavailable"` honestly if
   no marker is found
2. Requests execution through `execute_terminal_command`
3. Reads the real exit code/stdout/stderr from the result
4. If an LLM is configured, asks it to summarize that real output into a
   structured `TestResult`; otherwise falls back to a deterministic
   exit-code-based verdict (`0` → `passed`, else → `failed`) with the real
   stderr/stdout tail as the error detail
5. Returns the structured `TestResult` — `status="passed"` is only ever
   returned when the command actually exited `0`

## Workspace transfer

The primary transfer mechanism is the live bind mount established at
`Sandbox.create()` — anything the container writes under `/workspace`
appears on the host immediately (and vice versa), which is how
Developer's host-side file edits become visible to Tester's
container-side `pytest` run without any explicit copy step.
`Sandbox.copy_in()`/`copy_out()` handle the narrower case of moving a
*specific* file in addition to the mount: `copy_in`'s source must be
inside the sandbox's own workspace, and `copy_out`'s destination must be
inside a caller-specified `artifacts_root` — never an arbitrary host path
in either direction.

## Artifact handling

`backend/app/services/artifact_service.py`'s `collect_artifacts` is now
wired into `finalize` (`agents/graph.py`): if the Planner set
`Plan.expected_artifact_glob` (e.g. `"dist/*.whl"`) and the execution
passed, the workspace is globbed for matches and each one becomes a real
`Artifact` row (type inferred from extension: `.whl`/`.jar`/`.apk`/`.zip`/
`.tar.gz`). No artifact expected → the execution completes normally
either way, exactly as required.

Because Developer's edits and any Docker-run test/build command share the
same live bind-mounted workspace (Phase 1.4), a build artifact is
recorded by its workspace-relative path rather than copied elsewhere —
`Sandbox.copy_out` (implemented and tested since Phase 1.4) remains
available for a future scenario where a build produces output outside the
mounted workspace, but nothing in this workflow needs it today, so it
isn't forced in just to exercise it.

`expected_artifact_glob` is LLM-produced (via Planner), so it's treated
as untrusted input, not a trusted config value: `Path.glob()` supports
`..` segments and *will* walk outside its base directory if a pattern
contains them, so the pattern is rejected outright if it looks like an
escape attempt before globbing ever runs, and every match is
independently re-validated to be inside the workspace before being
recorded — two checks, neither trusting the other alone
(`tests/integration/test_artifact_collection.py`).

## Tool-calling loop

`StructuredLLMClient.generate_with_tools` (`agents/llm_client.py`) is what
Developer and Debugger call instead of the single-shot `generate`:

```
LLM (bind_tools) -> tool_calls? -> NO -> final with_structured_output call
                              -> YES -> validate+execute via BoundToolRunner
                                        -> ToolMessage appended -> LLM again
                                        (bounded by max_tool_calls)
```

An unauthorized tool name (`ToolPermissionError`) or an unknown one
(`ToolNotFoundError`) is never silently dropped or allowed to crash the
loop — the error is fed back to the model as the tool result, so it can
recover (e.g. by asking for a permitted tool instead) within the same
bounded loop
(`tests/unit/agents/test_tool_calling_loop.py::test_unauthorized_tool_call_is_recorded_and_model_recovers`).
Malformed tool arguments surface the same way, through the real tool's
own Pydantic validation inside `execute_tool`. The loop is tested against
the real `LangChainStructuredLLMClient` implementation with a stub chat
model (not just the test-only `FakeStructuredLLMClient`), so the
production tool-calling/recovery/limit logic is what's actually verified.

## Bounded autonomy

Four independent limits, all in `backend/app/core/config.py` and all
enforced, not just declared:

| Limit | Enforced where | Verified |
|---|---|---|
| `MAX_TOOL_CALLS_PER_AGENT` | `generate_with_tools`'s loop bound | `test_developer_tool_loop_is_bounded_by_max_tool_calls` |
| `MAX_TOTAL_TOOL_CALLS` | `agents/graph.py`'s `make_agent_node` computes `min(per_agent, remaining_total)` before each Developer/Debugger turn | `test_max_total_tool_calls_caps_developer_budget_across_the_run` — a second scripted write genuinely never reaches disk once the execution-wide budget is spent |
| `MAX_EXECUTION_SECONDS` | `asyncio.wait_for` around the whole `graph.ainvoke()` call in `execution_service.run_execution` | maps to `ExecutionStatus.TIMED_OUT`, never silently swallowed |
| `MAX_CONTEXT_CHARS` | `rag/retrieval/context_builder.py`'s `build_context`, called with `deps.max_context_chars` everywhere it's used | unchanged mechanism from Phase 1.3, now settings-driven |

Retries remain bounded by `MAX_DEBUG_RETRIES` as in Phase 1.3. Reaching
any limit produces a structured terminal state (`error`/`timed_out`), not
an infinite loop or a silent truncation an operator would have to notice
on their own.

## Cancellation

`backend/app/services/cancellation.py` is a deliberately in-process,
non-distributed signal — Phase 1 runs the whole graph inside one FastAPI
background task, so a process-local set is the correct scope, not a
premature distributed system. `POST /api/v1/executions/{id}/cancel`
requests cancellation; `agents/graph.py`'s `make_agent_node` checks it at
the start of every node and, if set, short-circuits straight to
`finalize` with `execution_status="cancelled"` → `ExecutionStatus.CANCELLED`.

**Granularity, stated plainly**: checked *between* agent turns, not
mid-tool-call — a command already running inside the Docker sandbox
completes before the next checkpoint rather than being force-killed
mid-execution. This is the practical Phase 1.5 scope, not a gap; a future
milestone could thread a cancellation token into `Sandbox.execute` itself
for finer granularity.

## RAG during execution

RAG is not an isolated indexing step — it participates in the actual run.
Orchestrator's initial retrieval (task-based) feeds Planner; beyond that,
query construction changes per stage (`agents/graph.py`'s
`_retrieval_query_for`): Developer retrieves against the task + the plan
steps it's about to implement, Debugger against the task + the actual
test failure it's diagnosing. Each re-retrieval replaces
`state.repository_context` for that turn (and downstream, via the node's
returned update) rather than agents reusing one static snapshot from the
very start of the run.

## Incremental re-indexing

`RepositoryIndexer.index_file` (`rag/ingestion/indexer.py`) re-chunks,
re-embeds, and replaces the vector chunks for exactly one file — the path
`agents/graph.py` triggers automatically after Developer's turn, for
every file it successfully created or modified. No file-watcher: this is
called synchronously, once, right after the change that made it stale,
reusing the same `replace_chunks_for_file` idempotency Phase 1.3's full
`index_repository` walk relies on. A file that becomes unreadable/binary/
deleted has its stale chunks cleared, not left behind
(`tests/integration/rag/test_incremental_reindex.py`).

## Secret scrubbing

`backend/app/security/secret_scrubber.py` — pattern-based redaction
(OpenAI-style keys, AWS access keys, GitHub tokens, PEM private key
blocks, bearer tokens, generic `key = "value"`-style credential
assignments) applied at the two actual persistence write-points:
`ToolCall` rows (`execute_tool`) and `AgentStep.output_metadata`
(`agents.graph.make_agent_node`) — before the database write, never after.
This is defense-in-depth, not a claim of perfect detection: repository/
command output is untrusted and can contain anything. What an agent
receives back from a tool call to reason with is deliberately **not**
scrubbed (a Developer fixing a hardcoded secret needs to see it to know
what to remove) — only what gets written to the database is redacted.
Verified end-to-end in
`tests/integration/execution/test_tester_docker_e2e.py`: a fixture whose
real pytest failure output contains a fake API key is run for real in
Docker, and the persisted `ToolCall.output` is confirmed redacted while
the key format itself (proving the pattern matched, not that the field
was empty) is gone.

## Persistence

Unchanged shape from Phase 1.2/1.3, now exercised by real executions:
every `execute_terminal_command` call produces a `ToolCall` row (tool
name, scrubbed input/output, status, duration, and — inside `output` —
the real exit code), and Tester's turn produces an `AgentStep` row like
every other agent.

## End-to-end fixtures

Two small, deterministic fixture projects prove both required flows for
real rather than asserting them:

**Fixture A — bug fix** (`playground/sample-project`, a minimal
calculator): task → RAG → plan → developer → test fails → debugger →
developer fixes → test passes → reviewer → success.
- `tests/integration/execution/test_tester_docker_e2e.py` — Tester runs
  real `pytest` in real Docker against the fixture (passes), against a
  version with a genuine bug introduced (fails, with the real assertion
  message surfaced), and against a fixture whose output contains a fake
  secret (confirmed scrubbed before persistence)
- `tests/integration/execution/test_debug_loop_real_execution.py` — the
  full cycle: a buggy fixture goes through Tester (fails, for real) →
  Debugger (investigates via real read-only tool calls) → Developer
  (applies a real `edit_file` call) → Tester (passes, for real) →
  Reviewer → `finalize`

**Fixture B — feature task** (`playground/feature-project`, a tiny
existing module): task → inspect → plan → implement → test → review →
success, with no pre-existing bug and no debug loop needed.
- `tests/integration/execution/test_feature_fixture_e2e.py` — Developer's
  tool-calling loop adds a new function and its test via two real
  `edit_file` calls, Tester's real `pytest` run passes on the first try
  (`retry_count == 0`, no Debugger step), Reviewer approves

In both, every Tester step runs genuine `pytest` in a genuine container
with a genuine exit code, and every Developer/Debugger tool call is
executed by the real tool registry against the real files on disk. What's
scripted (via `FakeStructuredLLMClient`, since no live LLM key exists in
this environment) is *which* tool calls each turn makes and each agent's
final structured summary — this is the documented graph-integration
boundary these tests leave for a live model to exercise for real: genuine
autonomous multi-turn reasoning is implemented and mechanically proven
correct end to end, but a live model choosing those tool calls itself is
validated separately (see Live Qwen validation below), not substituted
here.

## Live Qwen validation

Clearly separated from the deterministic suite, skip-gated on real
`LLM_API_KEY`/`LLM_BASE_URL` — never fabricated, never marked passed
without a real call actually succeeding:

- `backend/tests/test_llm_smoke.py` — raw connectivity, structured
  output (`with_structured_output` returns a real schema-valid instance),
  tool-calling behavior (the live model produces a well-formed
  `tool_calls` request), grounded context understanding (a structured
  answer that's actually correct given a small repository-context
  snippet, not just well-formed), and `Plan` production through the same
  `build_default_llm_client()` path `PlannerAgent` uses
- `tests/integration/execution/test_live_qwen_e2e.py` — the complete
  production path with **no fake LLM client anywhere**: Qwen → Planner →
  Developer (real model-driven tool calls) → Docker → Tester → Reviewer,
  against the calculator fixture

Run explicitly once credentials are configured: `pytest backend/tests/test_llm_smoke.py tests/integration/execution/test_live_qwen_e2e.py -v`.
In this development environment no live credentials are configured, so
these skip with an explicit reason and the rest of the suite runs
unaffected — reported honestly as `LIVE_QWEN_E2E = NOT_RUN`, never as
passed.

## Technology stack

- Python, FastAPI, Pydantic / Pydantic Settings
- LangChain (LLM/embeddings integration), LangGraph (agent orchestration)
- PostgreSQL with pgvector, SQLAlchemy (async), Alembic
- Redis
- Docker / Docker Compose (infra) + the `docker` CLI (sandbox)
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

Both expose health checks (`docker compose ps` shows their status). The
sandbox is **not** a compose service — it's ephemeral, built as a plain
image and spun up/destroyed per execution (see below), so it never
appears in `docker compose ps` and never occupies a host port.

### Build the sandbox image

```bash
docker build -t locopilot-sandbox-python:1.0 -f execution/docker/Dockerfile execution/docker
```

Required once (and after any Dockerfile change) before Tester's real
execution path or the Docker-backed test suite (`tests/integration/execution/`)
will work — both skip gracefully with a clear message if this image isn't
built yet, rather than failing. This is a Python-only image on purpose —
a Node/Java/etc. sandbox would be a sibling Dockerfile in
`execution/docker/`, built and referenced the same way;
`execution/docker/sandbox.py` takes `image` as a parameter and has no
language-specific logic.

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
- `GET http://localhost:8000/api/v1/tools` — registered tool schemas (now includes `execute_terminal_command`)
- `POST http://localhost:8000/api/v1/executions` — `{"task": "...", "workspace_path": "/path/to/a/repo"}`
  to run the real agent pipeline (including real sandboxed test execution
  if the target has a recognized project marker file) against a real
  local repo/directory
- `GET http://localhost:8000/api/v1/executions/{id}` — poll for status
- `POST http://localhost:8000/api/v1/executions/{id}/cancel` — request
  cancellation (checked between agent turns, see Cancellation above)

There is no endpoint that runs an arbitrary command — `execute_terminal_command`
is only reachable through the agent/tool architecture.

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
when their dependency isn't reachable/configured. The Docker-backed suite
(`tests/integration/execution/`) skips gracefully (with a clear message)
if Docker isn't running or `locopilot-sandbox-python:1.0` isn't built.
Agent and RAG unit tests never touch a live LLM, Postgres, or Docker at
all. Live-Qwen validation (see above) only runs when you explicitly
target it with real credentials configured; the default `pytest` run
always skips it cleanly rather than failing or faking it.

### Troubleshooting

- **`tests/integration/execution` all skip**: Docker isn't running, or
  the sandbox image isn't built yet — see "Build the sandbox image" above.
- **`ImageUnavailableError` / "No such image"**: same as above; the image
  build step was never run, or was run with a different tag than
  `locopilot-sandbox-python:1.0`.
- **A sandboxed command can't reach the network**: expected —
  `NetworkPolicy.DISABLED` is the default. A command needing package
  downloads etc. is a case for `NetworkPolicy.ALLOWED`, not yet wired to
  any agent-facing option.
- **Containers left running after a crashed test run**: shouldn't happen
  (every path destroys its container in a `finally` block, tested), but if
  it does: `docker ps -a --filter name=locopilot-sbx-` lists any survivors
  and `docker rm -f <name>` removes them — they're always named with the
  `locopilot-sbx-` prefix, never reused for anything else.

## Environment configuration

All configuration is environment-variable driven (see `.env.example`):
application settings, PostgreSQL/Redis connection info, LLM
provider/base URL/model/API key, embedding provider/base URL/model/API
key/dimension, and the bounded-autonomy limits (`MAX_DEBUG_RETRIES`,
`MAX_TOOL_CALLS_PER_AGENT`, `MAX_TOTAL_TOOL_CALLS`,
`MAX_EXECUTION_SECONDS`, `MAX_CONTEXT_CHARS`). Secrets are never
committed — `.env` is gitignored; only `.env.example` (placeholder
values) is tracked. No host environment variable is ever passed into a
sandbox container implicitly — see Container Security above.

## Project layout

```
backend/app/                    FastAPI application
backend/app/db/models/          SQLAlchemy models (incl. repository_chunk)
backend/app/db/repositories/    Persistence functions per model
backend/app/security/           Secret scrubbing
backend/app/services/           execution_service, tool_execution, artifact_service, cancellation
agents/                         LangGraph state, graph, and the 5 LLM-driven agents (incl. tool-calling loop)
tools/                          Controlled tool system: workspace, contracts, registry
tools/terminal/                 Contract, internal-only local executor, Docker executor, execute tool
rag/                             Chunking, embeddings, indexing (incl. incremental), retrieval, context building
execution/docker/                Sandbox implementation, Dockerfile, network/resource policy
database/migrations/             Alembic environment and migration scripts
playground/sample-project/       Fixture A — bug-fix deterministic fixture
playground/feature-project/      Fixture B — feature-task deterministic fixture
infrastructure/                  Docker Compose service configuration (Postgres/Redis only)
```

## Known limitations

- Cancellation is checked between agent turns, not mid-tool-call — a
  command already running inside Docker completes before the next
  checkpoint (see Cancellation above; this is a stated scope boundary,
  not an oversight).
- The cancellation signal is in-process, not distributed — correct for
  Phase 1's single-worker background-task model, would need a shared
  signal (e.g. Redis) for a future multi-worker deployment.
- `NetworkPolicy.RESTRICTED` (an egress allowlist) is reserved API surface
  — raises `NotImplementedError`, not silently falls back to something
  weaker.
- Both end-to-end fixture tests script every agent's LLM reasoning (no
  live LLM key in this environment); only the sandboxed `pytest`
  execution and the real tool calls are unscripted. Genuine autonomous
  multi-turn reasoning against a live model is implemented and covered by
  `test_live_qwen_e2e.py`, but that test itself reports
  `LIVE_QWEN_E2E = NOT_RUN` without credentials — see the final report for
  this milestone.
- The default embedding provider is a hashing bag-of-words vector, not a
  learned semantic model (unchanged from Phase 1.3).
- Prompt-injection mitigation is instructional, not a hard technical
  guarantee (unchanged from Phase 1.3) — though tool permission
  enforcement remains structural regardless, including for the new
  tool-calling loop (Debugger's schema restriction to read-only tools is
  enforced independently of what the model requests).
- Secret scrubbing is pattern-based defense-in-depth, not exhaustive
  detection — see `backend/app/security/secret_scrubber.py`'s docstring.
- No auth on the API — acceptable for a local single-user Phase 1 tool,
  not for anything exposed beyond localhost.
- Container resource limits rely on Docker Desktop's Linux VM on this
  development platform; exact cgroup behavior may differ on a bare-Linux
  Docker host.
