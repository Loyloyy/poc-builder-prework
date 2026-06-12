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
| t1     | GLM (open) | kata    |               |              |                |                 |          |
| t2     | GLM (open) | kata    |               |              |                |                 |          |
| repair | GLM (open) | kata    |               |              |                |                 |          |
| (opt)  | frontier   | kata    |               |              |                |                 |          |

## Verdict
- **OpenCode as a headless build engine** — does it hold up? (reliability, API friction, gotchas)
- **Harness loop** — does build→verify→repair recover from failures reliably?
- **Hermes as a learning layer** — worth the integration cost? What is the trace-adapter shape
  (field-by-field mapping from `harness/trace.py` to Hermes' expected trace input; what's missing)?
