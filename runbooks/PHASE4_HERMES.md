# Phase 4 — Characterize Hermes (explore, do NOT integrate)

**Objective:** understand Hermes' (Nous Research) learning loop, its skill format, and persistent
memory. **No** live integration with our harness. End with a concrete answer: *could our Phase-2
OpenCode traces feed Hermes' evolution loop, and what trace-format adapter would that require?*

**Success:** a written characterization of Hermes' loop + skill format + the trace-adapter answer.

## 0. Safety first — read the installer BEFORE running it
Hermes installs via pipe-to-bash. Do **not** pipe straight to a shell.
```bash
# Download, then READ it, then summarize to the user, THEN run.
curl -fsSL <hermes-install-url> -o /tmp/hermes-install.sh
less /tmp/hermes-install.sh          # what does it download? where does it write? sudo? curl|bash chains?
# Only after summarizing: bash /tmp/hermes-install.sh
```
Capture in findings.md: what the script installs, where, and anything it touches outside `~/.hermes`.

## 1. Point Hermes at a local/vLLM model (OpenAI-compatible)
Use the same OpenAI-compatible endpoint (vLLM directly) via Hermes' config — base URL +
key + served model id. Verify the config keys against Hermes' current docs (they drift).

## 2. Run one simple task and confirm the learning loop
- Give Hermes a single trivial task.
- Confirm a **skill** was generated:
  ```bash
  ls -la ~/.hermes/skills/
  ```
- Confirm **persistent memory** (SQLite) is populated:
  ```bash
  find ~/.hermes -name '*.db' -o -name '*.sqlite*'
  sqlite3 <the-db> '.tables'      # then inspect the populated tables
  ```
- Open ONE generated skill and summarize its format in findings.md: what fields/sections does a
  skill have (trigger, steps, code, metadata)? How is it keyed/retrieved?

## 3. Read the self-evolution loop
```bash
git clone https://github.com/NousResearch/hermes-agent-self-evolution
# Read PLAN.md; summarize how the DSPy + GEPA loop consumes EXECUTION TRACES to evolve skills.
```
Answer specifically:
- What does the loop ingest? (trace schema: steps, tool calls, outcomes, rewards/eval signal?)
- What does `evolve_skill` mutate, and what eval signal drives it (GEPA's reflective prompt evolution)?
- **Optional:** run one `evolve_skill` iteration on synthetic eval data; report what changed.

## 4. The deliverable question — trace adapter
Compare Hermes' expected trace input against our `harness/trace.py` schema
(`RunTrace`/`IterationTrace`: instruction, files_touched, test_rc, failing_summary, tokens, cost).

Answer in findings.md:
- **Could our Phase-2 traces feed Hermes' evolution loop?** (yes/no + why)
- **What adapter is required?** Field-by-field mapping from our trace JSON to Hermes' expected
  format — what we already emit, what's missing (e.g. explicit reward/eval signal, per-tool-call
  granularity, success label), and whether the adapter is a pure transform or needs new capture in
  the harness. Note: `final_status == "green"` + `iterations_to_pass` is a natural reward signal.
