# Phase 3 — Swap the sandbox to Kata, then probe the open model

**Objective:** re-run T1 + T2 with the container runtime set to **Kata** instead of default
runc; confirm isolation holds and the harness is unchanged except the runtime flag. Stretch:
swap the model to self-hosted vLLM and record the delta vs the frontier baseline.

**Success:** identical harness passes both tasks under Kata; you report the frontier-vs-open
delta (iterations-to-pass, success rate).

## 0. Preconditions
- Phases 1–2 are green under `HARNESS_RUNTIME=docker` (baseline traces saved).
- Kata registered as a NAMED Docker runtime (leaves the daemon default = runc untouched — important
  on a shared work box). On this server Kata is kata-static 3.31.0 at `/opt/kata`; register via
  `/etc/docker/daemon.json` (then `sudo systemctl reload docker`):
  ```json
  { "runtimes": { "kata": { "runtimeType": "/opt/kata/bin/containerd-shim-kata-v2" } } }
  ```
  Confirm it shows up:
  ```bash
  docker info | grep -iA4 -e runtimes -e "Default Runtime"
  ```
  The harness uses `--runtime kata`. If your registered name differs, change the ONE place it lives:
  `harness/runtime.py::_runtime_flag` (and `docker/run-workspace.sh`).

## 1. Smoke-test Kata isolation (independent of the harness)
```bash
# A Kata container runs in its own lightweight VM -> different kernel from the host.
docker run --rm --runtime kata python:3.11-slim uname -r
uname -r   # host kernel; the two should DIFFER under real Kata isolation
```
Record both kernel strings in findings.md as the isolation evidence.

## 2. Re-run the harness under Kata (no code change)
```bash
python3 -m harness.harness --task t1 --runtime kata
python3 -m harness.harness --task t2 --runtime kata
python3 -m harness.harness --task repair --runtime kata
```
- All three should reach `green` (repair in 2 iters). The only difference from Phase 2 is `--runtime`.
- New traces land in `traces/` tagged `_kata_`. Keep the `_docker_` ones for comparison.
- If T2's `pip install` fails under Kata egress policy, see the strict-egress note in
  `docker/Dockerfile.workspace` (pre-bake wheels + `--network none`).

## 3. Stretch — frontier comparison (the OPEN model is already our baseline)
Note: unlike the original plan, every run so far used the OPEN model (GLM via vLLM). So the "delta"
is measured the other way: optionally run with a FRONTIER model to compare iterations/variance.
Point `MODEL_API_*` at a frontier OpenAI-compatible endpoint AND repoint OpenCode's provider
(opencode.json baseURL/model + a matching OPENCODE_PROVIDER_ID), then re-run the three tasks.
```bash
# Frontier (e.g. OpenRouter). Also add a matching provider block in opencode.json + set
# OPENCODE_PROVIDER_ID to it, since OpenCode (not the harness) calls the model.
MODEL_API_BASE=https://openrouter.ai/api/v1 MODEL_API_KEY=<key> HARNESS_MODEL=<provider/model> \
  python3 -m harness.harness --task repair --runtime kata
```
Run each task a few times (open models are higher-variance) to get a success rate.

## 4. Record the delta (-> findings.md metrics table)
| task   | model         | runtime | iters-to-pass | success rate | wall-clock | tokens (in/out) |
|--------|---------------|---------|---------------|--------------|------------|-----------------|
| t1     | GLM (open)    | docker  | 1             |              | 44.8s      | 7585 / 17       |
| t2     | GLM (open)    | docker  | 1             |              | 18.2s      | 7525 / 112      |
| repair | GLM (open)    | docker  | 2             |              | 10.2s      | 13764 / 76      |
| t1     | GLM (open)    | kata    |               |              |            |                 |
| t2     | GLM (open)    | kata    |               |              |            |                 |
| repair | GLM (open)    | kata    |               |              |            |                 |
| ...    | frontier      | kata    |               |              |            |                 |

Pull the numbers straight from the JSON traces (`iterations_to_pass`, `total_*`).
