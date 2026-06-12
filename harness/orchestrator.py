"""Minimal OUTER orchestration loop — the poc-foundry nucleus, scoped to a probe.

    GOAL -> architect PLANS increments -> build each increment (coder = OpenCode) gated on the
    FULL acceptance suite -> repair until green or cap -> INTEGRATION gate (suite green) ->
    RUNNABLE gate (actually launch the app & probe it) -> repair if it won't start -> verdict.

The orchestration is THIS Python (deterministic). The LLM only acts INSIDE a step: the architect
plans (one direct model call), the coder edits files (OpenCode). Gates are exit codes, not opinions.

    python3 -m harness.orchestrator --goal notes_api [--runtime kata]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from .config import Config, load_config
from .harness import AGENT_TOOLS, _snapshot, _summarize_failures, _tail, repair_instruction
from .model_client import chat
from .opencode_client import OpenCodeClient, OpenCodeError
from .runtime import Workspace
from .trace import IterationTrace, OrchestrationTrace

REPO_ROOT = Path(__file__).resolve().parent.parent
GOALS_DIR = REPO_ROOT / "goals"
TRACES_DIR = REPO_ROOT / "traces"


def available_goals() -> list[str]:
    if not GOALS_DIR.is_dir():
        return []
    return sorted(p.name for p in GOALS_DIR.iterdir() if (p / "run.json").is_file())


def provision_goal(goal: str, cfg: Config) -> Path:
    src = GOALS_DIR / goal
    dst = cfg.workspace_root / f"goal_{goal}_{int(time.time())}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


# ---- PHASE 1: architect / plan -------------------------------------------
def architect_plan(cfg: Config, goal_md: str, test_src: str) -> list[dict]:
    system = "You are a software architect. Output ONLY a JSON array, no prose, no code fences."
    prompt = (
        f"GOAL:\n{goal_md}\n\nACCEPTANCE TESTS (do not change them):\n```python\n{test_src}\n```\n\n"
        "Break the build into 2-4 ordered increments toward the goal. Respond with ONLY a JSON "
        'array; each item {"name": "...", "description": "..."}.'
    )
    try:
        plan = _extract_json_array(chat(cfg, prompt, system=system))
    except Exception as e:  # noqa: BLE001 — plan is best-effort; degrade to a single increment
        print(f"[plan] architect call failed ({e}); using a single increment")
        plan = []
    return plan or [{"name": "build", "description": "Implement the entire goal."}]


def _extract_json_array(text: str) -> list[dict]:
    i, j = text.find("["), text.rfind("]")
    if i == -1 or j == -1 or j < i:
        return []
    try:
        arr = json.loads(text[i:j + 1])
    except Exception:  # noqa: BLE001
        return []
    return [{"name": str(x.get("name", "step")), "description": str(x.get("description", ""))}
            for x in arr if isinstance(x, dict)]


# ---- verification (full acceptance suite, in the sandbox) ----------------
def _verify(ws: Workspace, workspace: Path):
    if (workspace / "requirements.txt").exists():
        return ws.exec("pip install -q -r requirements.txt && python -m pytest -q")
    return ws.exec("python -m pytest -q")


def _step(client, sid, wsdir, ws, workspace, n, kind, instruction, baseline):
    """One build/repair step: drive the agent, snapshot the edit, verify. -> (ExecResult, IterationTrace)."""
    t0 = time.time()
    usage = client.send_instruction(sid, instruction, directory=wsdir, tools=AGENT_TOOLS)
    cur = _snapshot(workspace)
    touched = sorted(f for f, h in cur.items() if baseline.get(f) != h)
    result = _verify(ws, workspace)
    it = IterationTrace(
        n=n, kind=kind, instruction=instruction, files_touched=touched,
        test_rc=result.rc, test_stdout_tail=_tail(result.stdout + result.stderr),
        failing_summary=_summarize_failures(result.stdout + result.stderr) if result.rc != 0 else "",
        tokens_in=usage.tokens_in, tokens_out=usage.tokens_out,
        tokens_reasoning=usage.tokens_reasoning, cost_usd=usage.cost_usd,
        wall_s=round(time.time() - t0, 3),
    )
    return result, it


def run_goal(goal: str, cfg: Config) -> OrchestrationTrace:
    goal_dir = GOALS_DIR / goal
    run_cfg = json.loads((goal_dir / "run.json").read_text())
    test_file = run_cfg["test"]
    workspace = provision_goal(goal, cfg)
    wsdir = str(workspace)
    goal_md = (workspace / "GOAL.md").read_text()
    test_src = (workspace / test_file).read_text()

    trace = OrchestrationTrace(goal=goal, model=cfg.harness_model, runtime=cfg.runtime)

    # PHASE 1 — PLAN
    plan = architect_plan(cfg, goal_md, test_src)
    trace.plan = plan
    print(f"[{goal}] PLAN ({len(plan)} increments):")
    for k, inc in enumerate(plan, 1):
        print(f"   {k}. {inc['name']}: {inc['description']}")

    client = OpenCodeClient(cfg.opencode_base_url, cfg.opencode_password,
                            cfg.opencode_provider_id, cfg.harness_model,
                            agent=cfg.opencode_agent or None)
    try:
        sid = client.create_session(directory=wsdir)
        ctx = (f"# GOAL\n{goal_md}\n\n# Acceptance tests — do NOT edit `{test_file}`\n"
               f"```python\n{test_src}\n```\n")
        client.send_context(sid, ctx, directory=wsdir)

        with Workspace(workspace, cfg.workspace_image, runtime=cfg.runtime) as ws:
            baseline = _snapshot(workspace)
            result = None
            n = 0

            # PHASE 2 — build each increment, gate on the FULL suite (stop early once green)
            for inc in plan:
                if n >= cfg.max_iters:
                    break
                n += 1
                instr = (
                    f"Increment {n}: {inc['name']} — {inc['description']}\n"
                    f"Work toward making `python -m pytest -q` pass for the WHOLE goal. Edit "
                    f"`{run_cfg['stub']}` and `requirements.txt` as needed; do NOT edit `{test_file}`. "
                    f"Add packages to requirements.txt (the harness installs them in the sandbox)."
                )
                result, it = _step(client, sid, wsdir, ws, workspace, n, f"build:{inc['name']}",
                                   instr, baseline)
                baseline = _snapshot(workspace)
                trace.add(it)
                print(f"[{goal}] iter {n} build:{inc['name']}: pytest rc={result.rc}")
                if result.rc == 0:
                    break

            # PHASE 3 — repair until the suite is green or we hit the cap
            while (result is None or result.rc != 0) and n < cfg.max_iters:
                n += 1
                instr = (repair_instruction(result.stdout + result.stderr) if result
                         else "Implement the goal so the tests pass.")
                result, it = _step(client, sid, wsdir, ws, workspace, n, "repair", instr, baseline)
                baseline = _snapshot(workspace)
                trace.add(it)
                print(f"[{goal}] iter {n} repair: pytest rc={result.rc}")
                if result.rc == 0:
                    break

            trace.integration_ok = bool(result and result.rc == 0)

            # PHASE 4 — RUNNABLE gate: actually launch the app and probe it
            if trace.integration_ok:
                trace.iterations_to_integration = n
                rg = ws.launch_and_probe(run_cfg["launch"], run_cfg["probe"],
                                         run_cfg.get("expect_status", 200))
                trace.runnable_ok = rg.ok
                trace.runnable_detail = _tail(rg.stdout + rg.stderr)
                print(f"[{goal}] RUNNABLE gate: {'OK' if rg.ok else 'FAIL'}")

                tries = 0
                while not trace.runnable_ok and tries < 2 and n < cfg.max_iters + 2:
                    tries += 1
                    n += 1
                    instr = (
                        f"The app PASSES the tests but FAILS to launch as a server. Make "
                        f"`{run_cfg['launch']}` start and `{run_cfg['probe']}` return "
                        f"{run_cfg.get('expect_status', 200)}. Add any needed package (e.g. uvicorn) "
                        f"to requirements.txt. Launch output:\n```\n{trace.runnable_detail}\n```"
                    )
                    result, it = _step(client, sid, wsdir, ws, workspace, n, "runnable-repair",
                                       instr, baseline)
                    baseline = _snapshot(workspace)
                    trace.add(it)
                    rg = ws.launch_and_probe(run_cfg["launch"], run_cfg["probe"],
                                             run_cfg.get("expect_status", 200))
                    trace.runnable_ok = rg.ok
                    trace.runnable_detail = _tail(rg.stdout + rg.stderr)
                    print(f"[{goal}] RUNNABLE gate (retry {tries}): {'OK' if rg.ok else 'FAIL'}")

        trace.finalize("done" if (trace.integration_ok and trace.runnable_ok) else "not_done")
    except OpenCodeError as e:
        trace.finalize("error", f"OpenCode: {e}")
    except Exception as e:  # noqa: BLE001 — record any failure into the trace
        trace.finalize("error", repr(e))
    finally:
        client.close()

    out = trace.save(TRACES_DIR)
    print(f"[{goal}] VERDICT={trace.final_status} integration={trace.integration_ok} "
          f"runnable={trace.runnable_ok} iters={len(trace.iterations)} -> {out}")
    return trace


def main(argv: list[str] | None = None) -> int:
    goals = available_goals()
    ap = argparse.ArgumentParser(description="poc-builder-prework outer orchestration loop")
    ap.add_argument("--goal", required=True, choices=goals or None,
                    help=f"goal under goals/ ({', '.join(goals) or 'none found'})")
    ap.add_argument("--runtime", choices=["docker", "kata"],
                    help="override HARNESS_RUNTIME")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.runtime:
        cfg = Config(**{**cfg.__dict__, "runtime": args.runtime})

    trace = run_goal(args.goal, cfg)
    return 0 if trace.final_status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
