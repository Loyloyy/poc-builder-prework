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
import hashlib
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
    "t1": {"folder": "t1_roman", "stub": "roman.py", "test": "test_roman.py", "hidden": False},
    "t2": {"folder": "t2_fastapi", "stub": "app.py", "test": "test_health.py", "hidden": False},
    # Repair-demo: the test is HIDDEN from the agent (it works from SPEC only). The agent's first
    # guess can't match the exact wording the hidden test checks, so iter 1 fails deterministically
    # and the repair loop recovers — proving the loop without contrived sabotage.
    "repair": {"folder": "repair_demo", "stub": "greet.py", "test": "test_greet.py",
               "hidden": True},
    # Harness stress test: a trap-laden arithmetic evaluator (precedence/associativity/unary/
    # errors). Pure stdlib, deterministic, visible test. Exercises code-well + fix-well on real bugs.
    "calc": {"folder": "calc_eval", "stub": "calc.py", "test": "test_calc.py", "hidden": False},
    # Working-POC stress test: a small multi-endpoint URL-shortener service. Integration surface
    # (routing, 307 redirect, 404, validation, state) + harness-managed deps — where iteration
    # appears naturally if anywhere.
    "urlshort": {"folder": "url_shortener", "stub": "app.py", "test": "test_app.py",
                 "hidden": False},
}

# OpenCode's bash/webfetch run on the SERVE HOST, not our container — so we disable them and keep
# the agent to FILE EDITS only. The harness owns the sandbox: it installs requirements.txt and runs
# pytest in the container. T2's deps are thus ADDED BY THE AGENT to requirements.txt (an edit) and
# INSTALLED BY THE HARNESS — no host execution, matching the poc-foundry broker model.
AGENT_TOOLS = {"bash": False, "webfetch": False}


def provision(task: str, cfg: Config) -> Path:
    """Copy the task fixture into a fresh per-run workspace directory on the host. For hidden-test
    tasks the test file is EXCLUDED so the agent can't see it (the harness injects it at verify)."""
    meta = TASKS[task]
    src = TASKS_DIR / meta["folder"]
    dst = cfg.workspace_root / f"{task}_{int(time.time())}"
    if dst.exists():
        shutil.rmtree(dst)
    ignore = shutil.ignore_patterns(meta["test"]) if meta["hidden"] else None
    shutil.copytree(src, dst, ignore=ignore)
    return dst


def build_spec_context(workspace: Path, task: str) -> str:
    """The spec the agent sees = SPEC.md, plus the failing test (unless the test is hidden)."""
    meta = TASKS[task]
    spec = (workspace / "SPEC.md").read_text().strip()
    if meta["hidden"]:
        return f"# Spec\n{spec}\n"
    test = (workspace / meta["test"]).read_text()
    return (
        f"# Spec\n{spec}\n\n"
        f"# The failing test (do not edit it): {meta['test']}\n```python\n{test}\n```\n"
    )


def build_instruction(workspace: Path, task: str) -> str:
    meta = TASKS[task]
    stub = meta["stub"]
    if meta["hidden"]:
        return (
            f"Read `SPEC.md` in this directory and implement it by editing `{stub}`. There is a "
            f"HIDDEN test you cannot see; the harness runs it and reports any failure for you to "
            f"fix. Keep it minimal and stdlib-first."
        )
    reqs = (workspace / "requirements.txt").exists()
    editable = f"`{stub}`" + (" and `requirements.txt`" if reqs else "")
    dep_line = (
        " To add a Python package, put it in `requirements.txt` (the harness installs it in the "
        "sandbox before testing) — do NOT run shell commands yourself." if reqs else ""
    )
    return (
        f"Read `SPEC.md` and the test file `{meta['test']}` in this directory, then make "
        f"`python -m pytest -q` pass by editing {editable}. Do NOT modify `{meta['test']}`."
        f"{dep_line} Keep it minimal and stdlib-first."
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
        agent=cfg.opencode_agent or None,
    )

    try:
        wsdir = str(workspace)
        sid = client.create_session(directory=wsdir)
        client.send_context(sid, build_spec_context(workspace, task), directory=wsdir)

        meta = TASKS[task]
        with Workspace(workspace, cfg.workspace_image, runtime=cfg.runtime) as ws:
            instruction = build_instruction(workspace, task)
            baseline = _snapshot(workspace)   # content hashes, to detect what the agent edits
            for n in range(1, cfg.max_iters + 1):
                kind = "build" if n == 1 else "repair"
                t0 = time.time()
                usage = client.send_instruction(sid, instruction, directory=wsdir,
                                                 tools=AGENT_TOOLS)
                # diff BEFORE running pytest so we don't attribute .pytest_cache to the agent
                cur = _snapshot(workspace)
                touched = sorted(f for f, h in cur.items() if baseline.get(f) != h)
                baseline = cur
                # Harness owns the sandbox & verification. For hidden-test tasks, inject the real
                # test into /tmp (OUTSIDE /work so the agent never sees it via the bind mount) and
                # run it against the agent's module on /work. Otherwise install deps + run pytest.
                if meta["hidden"]:
                    ws.copy_in(str(TASKS_DIR / meta["folder"] / meta["test"]),
                               f"/tmp/{meta['test']}")
                    result = ws.exec(
                        f"cd /work && PYTHONPATH=/work python -m pytest /tmp/{meta['test']} -q")
                elif (workspace / "requirements.txt").exists():
                    result = ws.exec("pip install -q -r requirements.txt && python -m pytest -q")
                else:
                    result = ws.run_pytest()
                it = IterationTrace(
                    n=n, kind=kind, instruction=instruction,
                    files_touched=touched,
                    test_rc=result.rc,
                    test_stdout_tail=_tail(result.stdout + result.stderr),
                    failing_summary=_summarize_failures(result.stdout + result.stderr)
                        if result.rc != 0 else "",
                    tokens_in=usage.tokens_in, tokens_out=usage.tokens_out,
                    tokens_reasoning=usage.tokens_reasoning,
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


_SNAPSHOT_SKIP = {".pytest_cache", "__pycache__", ".git"}


def _snapshot(workspace: Path) -> dict[str, str]:
    """Map of relpath -> content sha1, so we can report exactly which files the agent changed
    (excludes test-cache / vcs noise). Diffing two snapshots gives an honest files_touched."""
    snap: dict[str, str] = {}
    for p in workspace.rglob("*"):
        rel = p.relative_to(workspace)
        if p.is_file() and not (set(rel.parts) & _SNAPSHOT_SKIP):
            snap[str(rel)] = hashlib.sha1(p.read_bytes()).hexdigest()
    return snap


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
