# poc-builder-prework

Stage-3 **pre-work**: validate three building blocks for an eventual "PoC Builder" pipeline,
in isolation, with deliberately trivial tasks so any failure is unambiguous.

1. **OpenCode** driven **headlessly** as a build engine.
2. A **harness loop** — build → run tests → on failure feed the error back and retry → stop at a
   verification gate.
3. **Hermes** (Nous Research) — characterize its learning loop (Phase 4, **explore only**, no integration).

> This is a **probe, not the product.** No retrieval/web-search stage, no live Hermes integration,
> no multi-agent orchestration, no production hardening. Keep it minimal and legible.

## ⚠️ Authored locally, RUN ON THE SERVER

This repo was scaffolded on a box that **cannot install or run** OpenCode, Docker, Kata, or Hermes,
so **nothing here has been executed or verified.** In particular, the OpenCode HTTP client
(`harness/opencode_client.py`) is written from early-2026 knowledge and **will** drift from the live
API. Treat the running server's `GET /doc` as ground truth and reconcile before trusting the client
(`scripts/verify_openapi.py`). Tell the user wherever reality diverges from this scaffold.

The build engine executes arbitrary code → **every build runs in a container, never on the host.**
Phases 1–2 use plain Docker; Phase 3 flips the runtime to **Kata** (one flag). Work only inside the
throwaway workspace root (default `~/stage3-prework/workspaces`).

## Setup (on the server)

No `pip install` and no venv. The harness host is **stdlib-only** (`urllib` + `subprocess`) — it
needs just the system `python3` and the `docker` CLI. Everything else installs inside containers
(pytest in the workspace image; fastapi by the agent). OpenCode is a standalone binary, not pip.

```bash
cp .env.example .env      # fill in model endpoint base/key, served model id, OpenCode password, caps
docker build -t poc-prework-workspace:latest -f docker/Dockerfile.workspace docker/

# Point OpenCode's build engine DIRECTLY at your model endpoint (no proxy). The REAL file holds
# your server IP + NFS model path, so it lives OUTSIDE the repo and is never committed:
mkdir -p ~/.config/opencode
cp docker/opencode.example.json ~/.config/opencode/opencode.json   # then edit baseURL + model id
```

## Phase map

| Phase | What | Entry point | Success gate |
|------|------|-------------|--------------|
| 0 | Install OpenCode, start server, save `/doc`, prove the model endpoint answers | `scripts/phase0_smoke.sh` then `scripts/verify_openapi.py` | server answers over HTTP; `/doc` saved; endpoint returns a completion |
| 1 | Drive OpenCode headlessly on T1 once (no loop) | `scripts/phase1_drive.py` | agent edits `roman.py`; `pytest` exits 0 |
| 2 | Full build→verify→repair loop on T1 + T2 | `python -m harness.harness --task t1` / `--task t2` | both green; T2 recovers from ≥1 induced failure; traces complete |
| 3 | Re-run under **Kata**; stretch: vLLM model | `runbooks/PHASE3_KATA.md` | identical harness passes under Kata; frontier-vs-open delta reported |
| 4 | Characterize **Hermes** | `runbooks/PHASE4_HERMES.md` | written characterization + trace-adapter answer |

## How OpenCode and the container share the workspace

The harness copies a task fixture into a fresh host directory under `HARNESS_WORKSPACE_ROOT`, then:
- **OpenCode** (running on the host) edits files in that directory — point `opencode serve` at it as
  the session's project/working directory, and select the scoped agent in `docker/opencode-agent.md`.
- The **container** (`harness/runtime.py`) bind-mounts the same directory at `/work` and runs
  `pytest -q` there. Edits the agent makes are seen immediately. The host is never the build target.

## The tasks

- **T1 `tasks/t1_roman/`** — implement `roman_to_int` (pure stdlib, deterministic, 5 asserts).
  `python3 -m harness.harness --task t1`
- **T2 `tasks/t2_fastapi/`** — FastAPI `GET /health` → `{"status":"ok"}`. The agent edits `app.py`
  (fixing a deliberately wrong import) and adds deps to `requirements.txt`; the **harness installs
  them + runs pytest in the container** (it owns the sandbox). `--task t2`
- **`repair` `tasks/repair_demo/`** — implements `greet()` from SPEC **only**; the test is HIDDEN
  from the agent (injected into the container at verify time, outside `/work`), so the first guess
  can't match the exact wording → the repair loop **deterministically** fires and recovers in iter 2.
  `--task repair`

## Outer loop (orchestration) — `harness/orchestrator.py`

The single-task harness above proves the **inner** loop. The **outer** loop is the poc-foundry
nucleus: take a GOAL, plan it, build increments, and verify the result actually *runs*.

```bash
python3 -m harness.orchestrator --goal notes_api [--runtime kata]
```

Phases — all deterministic Python; the LLM only acts *inside* a step:
1. **Plan** — the architect (a direct model call, `model_client.py`) decomposes the goal into increments.
2. **Build** — each increment is built by the coder (OpenCode), gated on the FULL acceptance suite.
3. **Repair** — on failure, feed the error back, up to the iteration cap.
4. **Integration gate** — the whole acceptance suite must be green.
5. **Runnable gate** — the harness actually launches the app (`uvicorn app:app`) and probes it, proving
   it *serves* (not just that `TestClient` can import it); a launch failure drives a repair.

Goals live in `goals/<name>/`: `GOAL.md` + acceptance tests + `run.json` (`stub`/`test`/`launch`/`probe`).

## Output

- **Traces:** one JSON per run under `traces/` (`harness/trace.py` schema) — machine-readable, the
  basis for Phase 4's trace-adapter analysis.
- **Findings:** fill in `findings.md` as you go — per-phase results, the metrics table, and the verdict.

## Layout

```
harness/      config.py · opencode_client.py · runtime.py · trace.py · harness.py
tasks/        t1_roman/ · t2_fastapi/   (SPEC.md + stub + failing test)
docker/       Dockerfile.workspace · opencode-agent.md · run-workspace.sh
scripts/      phase0_smoke.sh · verify_openapi.py · phase1_drive.py
runbooks/     PHASE3_KATA.md · PHASE4_HERMES.md
traces/ docs/ findings.md
```

See `DECISIONS.md` for design choices and `CLAUDE.md` for the working agreement.
