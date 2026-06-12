# Phase 3 — Swap the sandbox to Kata, then probe the open model

**Objective:** re-run T1 + T2 with the container runtime set to **Kata** instead of default
runc; confirm isolation holds and the harness is unchanged except the runtime flag. Stretch:
swap the model to self-hosted vLLM and record the delta vs the frontier baseline.

**Success:** identical harness passes both tasks under Kata; you report the frontier-vs-open
delta (iterations-to-pass, success rate).

## 0. Preconditions
- Phases 1–2 are green under `HARNESS_RUNTIME=docker` (baseline traces saved).
- Kata is installed and registered as a Docker runtime. Confirm the exact name:
  ```bash
  docker info | grep -iA4 -e runtimes -e "Default Runtime"
  ```
  Note the registered id (e.g. `io.containerd.kata.v2`, or `kata`/`kata-runtime` on older setups).
- If it differs from `io.containerd.kata.v2`, fix the ONE place it lives:
  `harness/runtime.py::_runtime_flag` (and `docker/run-workspace.sh`).

## 1. Smoke-test Kata isolation (independent of the harness)
```bash
# A Kata container runs in its own lightweight VM -> different kernel from the host.
docker run --rm --runtime io.containerd.kata.v2 python:3.11-slim uname -r
uname -r   # host kernel; the two should DIFFER under real Kata isolation
```
Record both kernel strings in findings.md as the isolation evidence.

## 2. Re-run the harness under Kata (no code change)
```bash
python -m harness.harness --task t1 --runtime kata
python -m harness.harness --task t2 --runtime kata
```
- Both should reach `green`. The only difference from Phase 2 is the `--runtime` flag.
- New traces land in `traces/` tagged `_kata_`. Keep the `_docker_` ones for comparison.
- If T2's `pip install` fails under Kata egress policy, see the strict-egress note in
  `docker/Dockerfile.workspace` (pre-bake wheels + `--network none`).

## 3. Stretch — swap to the self-hosted vLLM model (same proxy)
Point `MODEL_API_BASE`/`MODEL_API_KEY`/`HARNESS_MODEL` at the vLLM server; the harness is identical.
Remember to also repoint OpenCode's provider (opencode.json baseURL/model) at the vLLM endpoint.
```bash
# Use the served vLLM id the endpoint exposes (look it up; don't hardcode an old one).
# Confirm via:  curl $MODEL_API_BASE/models  -H "Authorization: Bearer $MODEL_API_KEY"
MODEL_API_BASE=http://<vllm-host>:<port>/v1 MODEL_API_KEY=not-needed HARNESS_MODEL=<served-vllm-id> \
  python -m harness.harness --task t1 --runtime kata
MODEL_API_BASE=http://<vllm-host>:<port>/v1 MODEL_API_KEY=not-needed HARNESS_MODEL=<served-vllm-id> \
  python -m harness.harness --task t2 --runtime kata
```
Run each task a few times (open models are higher-variance) to get a success rate.

## 4. Record the delta (-> findings.md metrics table)
| task | model        | runtime | iters-to-pass | success rate | wall-clock | tokens | cost |
|------|--------------|---------|---------------|--------------|------------|--------|------|
| T1   | frontier     | kata    |               |              |            |        |      |
| T1   | vLLM open    | kata    |               |              |            |        |      |
| T2   | frontier     | kata    |               |              |            |        |      |
| T2   | vLLM open    | kata    |               |              |            |        |      |

Pull the numbers straight from the JSON traces (`iterations_to_pass`, `total_*`).
