# CLAUDE.md — working agreement for this repo

**poc-builder-prework** = Stage-3 pre-work. Validate, in isolation, (1) OpenCode as a headless
build engine, (2) a build→verify→repair harness loop, (3) Hermes' learning loop (characterize
only). A probe, not the product. Read `README.md` for the phase map and `DECISIONS.md` before
non-trivial work.

## Hard rules
1. **Data hygiene.** Public-assumed repo. NEVER put server IPs, hostnames, served-model ids, NFS/model
   paths, ports, or keys in tracked files. Those live ONLY in the gitignored `.env`. Tracked files use
   placeholders (`<model-host>:<port>`, `<served-model-id>`, `<key-or-not-needed>`).
2. **No model names in app code.** Everything model/endpoint/cap-related is `.env`-driven via `harness/config.py`.
3. **`/doc` is ground truth.** The OpenCode client is written from early-2026 knowledge and WILL drift.
   Reconcile against the live `GET /doc` (`scripts/verify_openapi.py`) before trusting it; when the API
   differs, fix ONLY the `EP` table + (un)wrap helpers in `harness/opencode_client.py`.
4. **Containers always; no host pip/venv.** The build engine runs arbitrary code — every build/verify
   runs in a container, never on the host. The harness host itself is STDLIB-ONLY (urllib+subprocess):
   no `pip install`, no venv — just system python3 + docker CLI. pytest/fastapi install only inside
   containers; OpenCode is a standalone binary. Phase 3 = same harness, runtime flipped to Kata.
5. **Scope the agent.** Use `docker/opencode-agent.md` permission frontmatter: allow edit + test/run +
   installs inside the workspace; deny writes outside it and general egress.
6. **Cost control.** Cheap frontier tier for the loop; `HARNESS_SPEND_CAP_USD` aborts runaway runs;
   report tokens/cost per run (the trace carries them).

## Build / run model
- **Authored locally; RUN ON THE SERVER.** The local box can't install/run OpenCode/Docker/Kata/Hermes —
  nothing here is verified. Do NOT install packages or run the harness locally.
- The **user handles ALL git** (commit/push here, pull on server). Do NOT run git unless asked.
- Work only inside `~/stage3-prework/` on the server; never run destructive commands outside it.
- Hermes installs via pipe-to-bash — **read the script first**, summarize it, then run (see runbook).

## Status
Scaffold authored (Phases 0–2 as runnable code, Phases 3–4 as on-server runbooks). NOTHING run/verified
yet. First on-server step: `scripts/phase0_smoke.sh` → `scripts/verify_openapi.py` to reconcile the
OpenCode client against the live `/doc`, then Phases 1–2. Record everything in `findings.md`.

## Layout (`harness/`)
`config.py` (env-driven `Config`/`load_config`) · `opencode_client.py` (the only file to edit on API
drift — `EP` table + response-shape helpers) · `runtime.py` (`Workspace`; docker/kata switch) ·
`trace.py` (`RunTrace`/`IterationTrace` → JSON) · `harness.py` (the loop + CLI). Tasks in `tasks/`,
ops in `docker/`, entry scripts in `scripts/`, Phase 3–4 procedures in `runbooks/`.

## Key env knobs (all in gitignored `.env`; see `.env.example`)
- `MODEL_API_BASE` / `MODEL_API_KEY` / `HARNESS_MODEL` / `OPENCODE_PROVIDER_ID` (direct OpenAI-compatible; NO proxy)
- `OPENCODE_HOST` / `OPENCODE_PORT` / `OPENCODE_SERVER_PASSWORD`
- `HARNESS_MAX_ITERS` (=4) · `HARNESS_SPEND_CAP_USD` · `HARNESS_RUNTIME` (docker|kata) ·
  `HARNESS_WORKSPACE_ROOT` · `HARNESS_WORKSPACE_IMAGE`
