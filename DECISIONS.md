# DECISIONS — poc-builder-prework

Design choices, with the "why". Append as the probe runs on the server; record every place
reality diverges from this scaffold (the handover explicitly expects version/API drift).

## D1 — Python + httpx client, not the OpenCode JS/TS SDK
The harness and the wider Stage-2 stack are Python (LangGraph/httpx). The OpenCode server is an
OpenAPI HTTP service, language-agnostic, so a thin httpx client loses nothing and keeps one
language. Trade-off: we hand-maintain request/response shapes instead of getting a generated SDK —
mitigated by isolating all of it behind the `EP` table + helpers in `opencode_client.py` and the
`verify_openapi.py` reconciler.

## D2 — Direct OpenAI-compatible model endpoint, NO proxy (user ruling 2026-06-12)
The handover mentioned a LiteLLM proxy; the user vetoed it (consistent with the whole poc-foundry
line — no LiteLLM, direct OpenAI-compatible endpoints à la `ai-engineer-research`'s `build_chat_model`).
So OpenCode and the smoke test point STRAIGHT at one OpenAI-compatible endpoint (`MODEL_API_BASE` —
self-hosted vLLM, or a frontier/OpenRouter OpenAI-compatible API). The frontier<->vLLM swap (Phase 3)
= change `MODEL_API_BASE`/`MODEL_API_KEY`/`HARNESS_MODEL`; the harness is unchanged. OpenCode itself is
pointed at the endpoint via a custom openai-compatible provider (`docker/opencode.example.json`,
provider key = `OPENCODE_PROVIDER_ID`). Config stays env-driven; no model strings committed.

## D3 — Frontier first, vLLM second
Phases 1–3 run a cheap frontier model to isolate HARNESS bugs from MODEL-capability bugs. Only once
the harness is proven do we swap to self-hosted vLLM (Phase-3 stretch) and measure
iterations-to-pass / success-rate delta. Keeps failure attribution clean.

## D4 — OpenCode API treated as UNVERIFIED
Authored offline from early-2026 knowledge; the live `GET /doc` is ground truth. All endpoint paths
and payload/response shapes sit behind one banner in `opencode_client.py`; `scripts/verify_openapi.py`
diffs them against the spec before any run. On drift, edit only that file. We do NOT pretend the
client is proven.

UPDATE 2026-06-12 — RECONCILED against the live OpenCode **1.15.13** /doc on the server. Confirmed:
session create takes `model:{id,providerID}` + optional `agent`, working dir is the `?directory=`
QUERY param (not a body field); `POST /session/{sessionID}/message` is SYNCHRONOUS and returns the
completed turn `{info,parts}` with `info.tokens`/`info.cost`, so the polling loop was DELETED;
`noReply:true` is the real context-injection flag. Headless tool prompts avoided via a `permission`
block in opencode.json (edit/bash allow, webfetch deny) rather than per-session permission payloads.

## D5 — Sandbox: Docker now, Kata via one flag (Phase 3)
The build engine runs arbitrary code, so verification always runs in a container (`runtime.py`),
never on the host. The docker→kata switch is a single runtime flag (`_runtime_flag`) so Phase 3 is
"same harness, different isolation" — exactly what the success criterion asks. Strict "no egress"
for Phase 2's `pip install` is deferred via a documented wheels-prebake path rather than blocking
the probe.

## D6 — Induced failure baked into T2
T2's stub ships a deliberately wrong import (`FastApi`). This guarantees ≥1 repair iteration, which
the Phase-2 success criterion requires ("recovers from at least one induced failure"), and it's
deterministic — no flaky reliance on the model getting it wrong by chance.

## D7 — Traces are flat machine-readable JSON
`trace.py` keeps a deliberately flat schema (instruction, files_touched, test_rc, failing_summary,
tokens, cost; plus `final_status` + `iterations_to_pass`). This is what Phase 4 compares against
Hermes' expected trace input to answer the trace-adapter question. `green` + `iterations_to_pass`
doubles as a natural reward signal.

## D11 — Minimal OUTER orchestration loop (2026-06-12, after the one-shot finding)
Single-component build is solved by the model (5/5 one-shot), so the harness's value is ORCHESTRATION.
Built `harness/orchestrator.py`: GOAL → architect plans increments (one direct model call,
`model_client.py`, separate from the coder) → build each increment via OpenCode gated on the FULL
acceptance suite → repair → integration gate → RUNNABLE gate (`runtime.Workspace.launch_and_probe`
actually launches the app + probes it, proving it serves, not just imports) → verdict. Orchestration
is deterministic Python; the LLM only acts inside a step. Goals live in `goals/<name>/` (GOAL.md +
acceptance tests + run.json). This is the scoped nucleus of poc-foundry's deterministic outer harness;
the architect/coder split mirrors its roles. Inner-loop helpers (`_snapshot`, repair prompt, AGENT_TOOLS)
are reused from `harness.py`.

## D10 — Harness-managed sandbox env for T2 (user ruling 2026-06-12, post-T1-green)
OpenCode's bash runs on the SERVE HOST, not our container, so the agent does NOT execute anything.
Clean split (and matches the poc-foundry broker model): the **agent only edits files** (incl.
`requirements.txt`); the **harness installs deps + runs pytest in the container**. Chosen over
running `opencode serve` inside the container (heavier; OpenCode in the image + model reachability).
T2 repair trigger is realistic, not contrived: `requirements.txt` ships `fastapi` only, but
`fastapi.testclient` needs `httpx`; since the agent can't run tests (bash off) it usually only
learns this from the harness's failure → adds `httpx` → repair passes. Requires the workspace
container to reach PyPI (egress); if blocked on the server, fall back to pre-baked wheels
(docker/Dockerfile.workspace) + `--network none`.

## D9 — Stdlib-only harness host: no pip, no venv (user ruling 2026-06-12)
The user wants nothing installed on the host (no pip/venv) — only docker/kata. The single host-side
dependency was `httpx` in the OpenCode client; replaced with stdlib `urllib`. Result: the harness runs
on bare `python3` + the `docker` CLI, zero installs. pytest installs only in the workspace image,
fastapi only inside the container (agent), OpenCode is a standalone binary. Fully containerizing the
harness ITSELF is possible (orchestrator container + mounted docker.sock) but adds a docker.sock +
host-path-mapping wrinkle for the bind-mounted workspaces; deferred since the host now needs no
packages anyway. `pyproject.toml` runtime deps = [] accordingly.

## D8 — Turn-completion detection is polling, not SSE
`opencode_client._await_turn` polls the message list and treats "new assistant message with usage /
finish signal" as done. Rationale: most version-robust across OpenCode builds. If the live `/doc`
exposes a clean `/event` SSE stream, switching to it is a localized change. VERIFY the completion
signal on the server.
