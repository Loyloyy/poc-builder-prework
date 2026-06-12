"""The harness loop: provision -> drive OpenCode -> verify -> repair -> gate.

    build  : send the failing test + one-line spec, instruct the agent to make it pass
    verify : run `pytest -q` INSIDE the container (host is never the build target)
    repair : on failure, feed the captured pytest output back as a repair instruction
    gate   : stop on green, or at HARNESS_MAX_ITERS, or if cost exceeds HARNESS_SPEND_CAP_USD
    trace  : write a machine-readable JSON trace under traces/

Run on the server:
    python -m harness.harness --task t1
    python -m harness.harness --task t2 --runtime kata

PRECONDITION: `opencode serve` is running and its project/working directory is the per-run
workspace (the agent edits files there; the container sees them via bind mount). See README
"How OpenCode and the container share the workspace". The OpenCode client paths are UNVERIFIED
until `scripts/verify_openapi.py` passes against the live /doc.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from .config import Config, load_config
from .opencode_client import OpenCodeClient, OpenCodeError
from .runtime import Workspace
from .trace import IterationTrace, RunTrace

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"
TRACES_DIR = REPO_ROOT / "traces"

TASKS = {
    "t1": ("t1_roman", "roman.py", "test_roman.py"),
    "t2": ("t2_fastapi", "app.py", "test_health.py"),
}


def provision(task: str, cfg: Config) -> Path:
    """Copy the task fixture into a fresh per-run workspace directory on the host."""
    folder, _, _ = TASKS[task]
    src = TASKS_DIR / folder
    dst = cfg.workspace_root / f"{task}_{int(time.time())}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def build_spec_context(workspace: Path, task: str) -> str:
    """The spec the agent sees = the failing test file + the one-line SPEC.md."""
    _, _, test_file = TASKS[task]
    spec = (workspace / "SPEC.md").read_text().strip()
    test = (workspace / test_file).read_text()
    return (
        f"# Spec\n{spec}\n\n"
        f"# The failing test (do not edit it): {test_file}\n```python\n{test}\n```\n"
    )


def build_instruction(workspace: Path, task: str) -> str:
    folder, stub, test_file = TASKS[task]
    return (
        f"Working directory: {workspace}\n"
        f"Make `python -m pytest -q` pass. Edit ONLY `{stub}` (and add dependencies if the "
        f"test needs them). Do NOT modify `{test_file}`. Keep the solution minimal and "
        f"stdlib-first. When done, the tests must pass."
    )


def repair_instruction(test_tail: str) -> str:
    return (
        "The tests still fail. Here is the pytest output — diagnose and fix the cause, then "
        "ensure the tests pass:\n\n```\n" + test_tail[-3000:] + "\n```"
    )


def _tail(s: str, n: int = 2000) -> str:
    return s[-n:]


def run_task(task: str, cfg: Config) -> RunTrace:
    workspace = provision(task, cfg)
    trace = RunTrace(task=task, model=cfg.harness_model, runtime=cfg.runtime)

    client = OpenCodeClient(
        base_url=cfg.opencode_base_url,
        password=cfg.opencode_password,
        provider_id=cfg.opencode_provider_id,
        model=cfg.harness_model,
    )

    try:
        sid = client.create_session(title=f"poc-prework-{task}", directory=str(workspace))
        client.send_context(sid, build_spec_context(workspace, task))

        with Workspace(workspace, cfg.workspace_image, runtime=cfg.runtime) as ws:
            instruction = build_instruction(workspace, task)
            for n in range(1, cfg.max_iters + 1):
                kind = "build" if n == 1 else "repair"
                t0 = time.time()
                usage = client.send_instruction(sid, instruction)
                result = ws.run_pytest()
                it = IterationTrace(
                    n=n, kind=kind, instruction=instruction,
                    files_touched=_changed_files(workspace),
                    test_rc=result.rc,
                    test_stdout_tail=_tail(result.stdout + result.stderr),
                    failing_summary=_summarize_failures(result.stdout + result.stderr)
                        if result.rc != 0 else "",
                    tokens_in=usage.tokens_in, tokens_out=usage.tokens_out,
                    cost_usd=usage.cost_usd, wall_s=round(time.time() - t0, 3),
                )
                trace.add(it)
                print(f"[{task}] iter {n} ({kind}): pytest rc={result.rc} "
                      f"cost=${usage.cost_usd:.4f}")

                if result.rc == 0:
                    trace.finalize("green")
                    break
                if sum(i.cost_usd for i in trace.iterations) > cfg.spend_cap_usd:
                    client.abort(sid)
                    trace.finalize("spend_cap",
                                   f"exceeded ${cfg.spend_cap_usd} spend cap")
                    break
                instruction = repair_instruction(it.test_stdout_tail)
            else:
                trace.finalize("cap_reached", f"no green after {cfg.max_iters} iters")
    except OpenCodeError as e:
        trace.finalize("error", f"OpenCode: {e}")
    except Exception as e:  # noqa: BLE001 — record any failure into the trace
        trace.finalize("error", repr(e))
    finally:
        client.close()

    out = trace.save(TRACES_DIR)
    print(f"[{task}] final={trace.final_status} iters_to_pass={trace.iterations_to_pass} "
          f"total_cost=${trace.total_cost_usd:.4f} -> {out}")
    return trace


def _changed_files(workspace: Path) -> list[str]:
    """Best-effort: files modified in the last 10 minutes, relative to workspace.
    (No git in the throwaway workspace; mtime is good enough for the trace.)"""
    cutoff = time.time() - 600
    out = []
    for p in sorted(workspace.rglob("*")):
        if p.is_file() and p.stat().st_mtime >= cutoff and "__pycache__" not in p.parts:
            out.append(str(p.relative_to(workspace)))
    return out


def _summarize_failures(output: str) -> str:
    """Pull the most useful lines out of pytest output for the trace + repair prompt."""
    keep = [ln for ln in output.splitlines()
            if ln.startswith(("E ", "FAILED", "ERROR")) or "Error" in ln]
    return "\n".join(keep[-12:])[:1500]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="poc-builder-prework harness loop")
    ap.add_argument("--task", choices=sorted(TASKS), required=True)
    ap.add_argument("--runtime", choices=["docker", "kata"],
                    help="override HARNESS_RUNTIME (Phase 3 uses kata)")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.runtime:
        cfg = Config(**{**cfg.__dict__, "runtime": args.runtime})

    trace = run_task(args.task, cfg)
    return 0 if trace.final_status == "green" else 1


if __name__ == "__main__":
    sys.exit(main())
