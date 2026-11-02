# LocoPilot — session summary (2 Nov 2026)

## Result

LocoPilot runs locally and is deployed on free tiers:

| Part | Where | URL |
|---|---|---|
| Frontend (Next.js) | Vercel, project `loco-pilot` | https://loco-pilot.vercel.app |
| Backend (FastAPI) | Render web service `locopilot-api` | https://locopilot-api.onrender.com |
| Database (Postgres + pgvector) | Render `locopilot-db` | internal |

`locopilot.vercel.app` was already taken by someone else, so `loco-pilot.vercel.app` is used.
All code lives on the **`deploy`** branch of `iamankoo/Loco-Pilot`; `main` was not changed.

An end-to-end run from the live site worked: task → Planner → Developer → Tester → Reviewer → **passed**,
and the finished files were saved into a folder on the user's own computer, ready to open in VS Code.

## Problems found and fixed

| Problem | Cause | Fix |
|---|---|---|
| `docker compose up` failed | Docker Desktop was not running | Start Docker Desktop first |
| Frontend build error (`Fraunces`) | Turbopack cannot handle an explicit `weight` list plus `style` on a variable font | Removed the `weight` option in `frontend/app/layout.tsx` |
| `alembic upgrade head`: "No script_location" and "password authentication failed" | Commands were run from `backend/` instead of the project root, so `.env` was not read and an old Postgres on port 5432 was used | Run everything from the project root |
| Every execution would fail | The configured NVIDIA model `nemotron-3-nano-30b-a3b` was retired on 2026-09-01 | Switched Planner/Developer/Debugger/default to `nvidia/nemotron-3.5-lightning-30b-a3b` (already used by the Reviewer) |
| "needs review" on a simple web page | The agent's `start_server.sh` could not start a runtime, even though the HTML was right | Served the page manually; the Docker runtime layer was not changed |
| Render blueprint rejected | Render allows only one free Key Value (Redis) instance per workspace | Redis made optional (`REDIS_ENABLED=false`); removed from `render.yaml` |
| Vercel site returned 404 | Project was created from the CLI with its framework unset, so Next.js deployed as a static site | Set the framework to Next.js and redeployed |
| Run button disabled on the hosted site | The "Local folder…" workspace option asks for a path on the server | Hidden when the backend is not on localhost |
| Save failed: "Workspace root does not exist" | Render's free disk is wiped on every redeploy or idle spin-down | Files are now also stored in the database after every run and restored when needed |

## New features

- **Access token.** Set `ACCESS_TOKEN` on the backend and every `/api/*` request needs `Authorization: Bearer <token>`.
  The site asks for the token once and keeps it in that browser only. With no token set (local development) nothing changes.
- **Save to your own computer.** Before a run the site asks you to choose a folder (browser permission prompt,
  Chrome/Edge). When the run finishes, the project is written to `<your folder>/<project-name>/`. It saves
  automatically once per run; a "Save to my computer" panel saves again on request.
- **File endpoints.** `GET /api/v1/projects/{id}/files/tree` and `/files/content?path=` (sandboxed to the workspace).
- **Durable project copy.** New table `project_files` (migration `a3c91e5d7b42`). A snapshot is taken after every
  execution; listing and downloads fall back to it, and later runs rebuild the workspace from it.
- **Deployment files.** `render.yaml` (Render blueprint) and `docs/DEPLOYMENT.md`.

## Run locally

```powershell
# 1. Start Docker Desktop, then from the project root:
docker compose up -d
.\.venv\Scripts\Activate.ps1
alembic upgrade head
uvicorn backend.app.main:app --reload      # http://localhost:8000

# 2. In a second terminal:
cd frontend
npm run dev                                 # http://localhost:3000
```

Always run these from the project root (backend) and `frontend/` (frontend), not from `backend/`.

## Run the generated project

The output is saved into the folder you chose. For a plain HTML page, open `index.html`, or:

```powershell
python -m http.server 5500     # then open http://localhost:5500
```

## Deploy / update

- **Backend:** pushing to the `deploy` branch makes Render redeploy automatically (about 1–2 minutes; migrations run at start-up).
- **Frontend:** from `frontend/`, run `vercel deploy --prod --yes`. `NEXT_PUBLIC_API_BASE_URL` (the Render URL) is set in the Vercel project.
- **Secrets:** `LLM_API_KEY`, `EMBEDDING_API_KEY` and `ACCESS_TOKEN` live only in Render's Environment tab. Nothing secret is in the repository.

## Known limits

- **No Docker on Render.** The isolated test sandbox and the "Running Locally" preview do not work in the cloud
  (they do locally), so cloud runs can end as `needs_review`. The code is still planned, written and reviewed.
- **Free-tier behaviour.** The Render API sleeps when idle and takes about a minute to wake. The free Postgres
  expires after 30 days. The server's disk is temporary; the database copy is the durable one.
- **Browser support.** Saving to a folder needs a Chromium browser (Chrome, Edge).
- **Not verified:** one live-LLM test, `tests/integration/test_independent_code_review.py`, failed in a full local run;
  it was not checked against the code before these changes. The old Wonderyard and C++ calculator executions
  from earlier still show as `running` in the local database (stale).
- **Not production software.** Single-user, no accounts. The access token is a shared secret.

## Other notes

- The Render CLI was installed at `C:\Users\iaman\AppData\Local\render-cli\bin\render.exe` (v2.34.0, checksum verified) but was never logged in.
- The local `.env` was edited (models above); the original is backed up at `%TEMP%\env.backup`.
- A Vercel deployment-protection bypass token was generated on the `loco-pilot` project during testing; it can be deleted in the project settings.
- `1.ipynb` and `req.txt` are unrelated untracked files and were not committed.
