# findings.md — poc-builder-prework (FILL IN ON THE SERVER)

The deliverable. Fill each section as you run the phases. Note every place reality diverged from
the scaffold (versions, commands, API paths, model strings).

## Environment actually used
- OpenCode version: `<opencode --version>`
- Install method that worked: `<...>`
- Model endpoint (direct, no proxy): base `<...>` · frontier model id `<...>` · vLLM served id `<...>`
- Docker version / runtimes: `<docker info | grep -i runtime>`
- Kata version: `<...>`

## Per-phase: what worked / what broke
### Phase 0 — install & smoke test
- Commands run, server start flags, `/doc` title+version, proxy routing result:
- API divergences found by `verify_openapi.py` (and what was changed in `opencode_client.py`):

### Phase 1 — drive OpenCode once on T1
- Files changed, wall-clock, tokens/cost (from the trace):
- Did the single build pass?

### Phase 2 — harness loop (T1 + T2)
- T1 result; T2 result; did the repair loop recover from the induced wrong-import failure?
- Trace files produced:

### Phase 3 — Kata + open model
- Kata isolation evidence (host vs container kernel):
- T1/T2 under Kata: pass? unchanged harness?
- vLLM swap results:

### Phase 4 — Hermes characterization
- Install-script summary (what it does, where it writes):
- Skill format (fields/sections of one generated skill); memory DB tables:
- DSPy + GEPA loop: what it ingests, what `evolve_skill` mutates, eval signal:

## Metrics table
(Model kept generic here — real served id/host live only in the gitignored .env / traces.)
| task   | model      | runtime | iters-to-pass | success rate | wall-clock (s) | tokens (in/out) | cost ($) |
|--------|------------|---------|---------------|--------------|----------------|-----------------|----------|
| t1     | GLM (open) | docker  | 1             | TBD          | 44.8           | 7585 / 17       | 0.00     |
| t2     | GLM (open) | docker  | 1             | TBD          | 18.2           | 7525 / 112      | 0.00     |
| repair | GLM (open) | docker  | 2             | TBD          | 10.2           | 13764 / 76      | 0.00     |
| calc   | GLM (open) | docker  | 1             | —            | 86.9           | 8714 / 17*      | 0.00     |
| urlshort | GLM (open) | docker | 1            | —            | 29.0           | 8323 / 313      | 0.00     |
| t1     | GLM (open) | kata    | 1             | TBD          | (in trace)     | (in trace)      | 0.00     |
| t2     | GLM (open) | kata    | 1             | TBD          | (in trace)     | (in trace)      | 0.00     |
| repair | GLM (open) | kata    | 2             | TBD          | (in trace)     | (in trace)      | 0.00     |
| (opt)  | frontier   | kata    |               |              |                |                 |          |

Kata isolation evidence: guest-VM kernel `6.18.28` vs host kernel `6.8.0-124-generic` (separate
kernels = own VM). Identical iters docker↔kata; pip egress works from inside the VM; `docker cp`
(hidden-test inject) works into a Kata container.

\* **Token counts are unreliable** for this vLLM/GLM endpoint — OpenCode's reported
`message.info.tokens.output` under-counts badly (e.g. calc: 17 output tokens for 87s of real work
producing a full parser). **Use wall-clock as the cost signal**, not tokens, until this is traced.

**KEY FINDING — the build engine one-shots single components.** Across 5 tasks (roman, fastapi,
trap-laden expression evaluator, multi-endpoint URL shortener) GLM-5 reached green in **1 iteration**
every time. The repair loop only fired on `repair`, where we deliberately HID the test. Implication:
at single-component granularity, a strong open model + a correct harness ≈ one-shot; the harness's
iterate/fix loop is a proven safety net but rarely needed there. The unsolved problem — and where a
harness actually earns its keep — is ORCHESTRATION: decompose a goal → build increments → integrate →
verify it RUNS → stay aligned to the goal. That (not single-component repair) is the next thing to build.

## Verdict
- **OpenCode as a headless build engine — YES, it holds up.** Driven via a stdlib HTTP client
  (OpenCode 1.15.13), it edited only the intended files, respected "don't touch the test," and added
  a dependency to `requirements.txt` on its own. Friction was all one-time API reconciliation against
  the live `/doc`: session-create binds `model:{id,providerID}` + optional `agent`; working dir is the
  `?directory=` query param (not a body field); `POST .../message` is synchronous (no polling); context
  via `noReply:true`. Key gotcha: OpenCode's `bash`/`webfetch` tools run on the **serve host, not the
  container** — so we disable them and let the harness own the sandbox (install + verify in-container).
- **Harness loop — YES, recovers reliably.** build → verify-in-container → feed error back → repair →
  gate, demonstrated by the `repair` task (iter 1 fails on a hidden test, iter 2 recovers in ~3.6s).
  Runtime-agnostic: identical results under docker and Kata (only `--runtime` changes). Kata gives
  hardware-VM isolation per build (guest kernel ≠ host kernel) at no change to the harness.
- **Hermes as a learning layer** — [Phase 4 pending] worth the integration cost? What is the
  trace-adapter shape (field-by-field mapping from `harness/trace.py` to Hermes' expected trace input;
  what's missing)? `final_status`/`iterations_to_pass`/`failing_summary` are natural reward+signal.
