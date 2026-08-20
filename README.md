# LocoPilot

LocoPilot is an autonomous AI software engineering agent. It accepts a
software task and a repository, understands the codebase, plans an
implementation, modifies code through controlled tools, runs tests,
diagnoses and fixes failures, reviews the resulting diff, and returns a
structured engineering result. It is not a chatbot — there is no
conversational interface; the unit of interaction is a task submitted to
an execution.

## Status: Phase 1.4 — Docker Sandbox + Real Execution

Phases 1.1 (foundation), 1.2 (persistence + controlled tools), and 1.3
(LangGraph agents + RAG) are done. This milestone turns the Phase 1.2
terminal *contract* into a real, isolated Docker execution environment and
activates Tester's real path: it now genuinely runs a project's test
command inside a sandboxed container and reports the real result. It does
**not** yet include a professional dashboard, autonomous project creation,
or multi-user features — see Known Limitations.

What's implemented:

- A real Docker sandbox (`execution/docker/sandbox.py`): create/start/
  execute/copy_in/copy_out/inspect/destroy, hardened by default (non-root,
  read-only root filesystem, all capabilities dropped, no-new-privileges,
  memory/CPU/pids limits, network disabled) — verified against this
  project's actual Docker environment, not just asserted
- `DockerTerminalExecutor` (`tools/terminal/docker_executor.py`) — the
  real production implementation of Phase 1.2's `TerminalCommandRequest ->
  TerminalCommandResult` contract, replacing nothing (the internal-only
  `LocalDevTerminalExecutor` still exists for tests, still never
  agent-facing)
- The first execute-capable tool, `execute_terminal_command`, registered
  in the tool registry with `Permission.EXECUTE`
- Tester's real path (Phase 1.3 left this intentionally unavailable):
  detects an appropriate test command from real project marker files, runs
  it through the tool layer, and interprets the actual exit code/stdout/
  stderr — with **zero changes** to the graph, other agents, or state
  schema; only `TESTER_PERMISSIONS` gained `EXECUTE`, exactly as predicted
  in the Phase 1.3 report
- A first real secret-scrubbing layer (`backend/app/security/secret_scrubber.py`),
  applied before `ToolCall`/`AgentStep` persistence
- A minimal, reproducible sandbox image (`locopilot-sandbox-python:1.0`)
  and a deterministic fixture project (`playground/sample-project`) used
  to prove real, sandboxed test execution end to end

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

`Sandbox.copy_out(container_path, host_path, artifacts_root=...)` is
implemented and tested (boundary enforcement: a destination outside
`artifacts_root` raises `ArtifactTransferError`) but is not yet invoked by
any agent — no current agent's job description includes "select and
collect a build artifact" (Developer/Tester deal in source edits and test
results, not `.whl`/`.jar`/`.apk` output). The foundation the Phase 1.2
`Artifact` model needs is real and ready: a real `copy_out` mechanism with
a real safety boundary, prepared for a future milestone to wire "Tester
detects a build produced `dist/app.whl`" → `copy_out` → `create_artifact`.

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

## End-to-end fixture

`playground/sample-project` is a minimal calculator (implementation +
pytest suite) used to prove real execution rather than asserting it:

- `tests/integration/execution/test_tester_docker_e2e.py` — Tester runs
  real `pytest` in real Docker against the fixture (passes), against a
  version with a genuine bug introduced (fails, with the real assertion
  message surfaced), and against a fixture whose output contains a fake
  secret (confirmed scrubbed before persistence)
- `tests/integration/execution/test_debug_loop_real_execution.py` — the
  full second half of the Phase 1.4 requirement: a buggy fixture goes
  through Tester (fails, for real) → Debugger → Developer (applies a real
  file edit) → Tester (passes, for real) → Reviewer → `finalize`. Every
  Tester step runs genuine `pytest` in a genuine container with a genuine
  exit code; what's scripted (via `FakeStructuredLLMClient`, since no live
  LLM key exists in this environment) is every agent's *reasoning* output
  — this is the same, already-established Phase 1.3 testing methodology
  applied here, and it is the documented graph-integration boundary this
  milestone leaves for a live LLM to exercise for real: genuine
  autonomous multi-turn debugging is implemented and mechanically proven
  correct, but not exercised against a live model in this environment.

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
all.

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
key/dimension, and `MAX_DEBUG_RETRIES`. Secrets are never committed —
`.env` is gitignored; only `.env.example` (placeholder values) is tracked.
No host environment variable is ever passed into a sandbox container
implicitly — see Container Security above.

## Project layout

```
backend/app/                    FastAPI application
backend/app/db/models/          SQLAlchemy models (incl. repository_chunk)
backend/app/db/repositories/    Persistence functions per model
backend/app/security/           Secret scrubbing
backend/app/services/           execution_service (API<->graph boundary), tool_execution
agents/                         LangGraph state, graph, and the 5 LLM-driven agents
tools/                          Controlled tool system: workspace, contracts, registry
tools/terminal/                 Contract, internal-only local executor, Docker executor, execute tool
rag/                             Chunking, embeddings, indexing, retrieval, context building
execution/docker/                Sandbox implementation, Dockerfile, network/resource policy
database/migrations/             Alembic environment and migration scripts
playground/sample-project/       Deterministic fixture project for real end-to-end tests
infrastructure/                  Docker Compose service configuration (Postgres/Redis only)
```

## Known limitations

- Artifact collection (`Sandbox.copy_out` + `Artifact` persistence) is
  implemented and tested but not yet invoked by any agent.
- `NetworkPolicy.RESTRICTED` (an egress allowlist) is reserved API surface
  — raises `NotImplementedError`, not silently falls back to something
  weaker.
- The genuine debug-loop end-to-end test scripts every agent's LLM
  reasoning (no live LLM key in this environment); only the sandboxed
  `pytest` execution itself is unscripted. Real autonomous multi-turn
  debugging against a live model is implemented but untested here.
- The default embedding provider is a hashing bag-of-words vector, not a
  learned semantic model (unchanged from Phase 1.3).
- Prompt-injection mitigation is instructional, not a hard technical
  guarantee (unchanged from Phase 1.3) — though tool permission
  enforcement remains structural regardless.
- Secret scrubbing is pattern-based defense-in-depth, not exhaustive
  detection — see `backend/app/security/secret_scrubber.py`'s docstring.
- No auth on the API — acceptable for a local single-user Phase 1 tool,
  not for anything exposed beyond localhost.
- Container resource limits rely on Docker Desktop's Linux VM on this
  development platform; exact cgroup behavior may differ on a bare-Linux
  Docker host.
