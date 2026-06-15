"""OUTER orchestration loop as a LangGraph graph — the poc-foundry nucleus, scoped to a probe.

Same pipeline as the hand-rolled loop it replaces, now expressed as a directed graph:

    plan ─► build ─►(rc==0)──────────────► integration_gate ─►(green)─► runnable_gate ─►(ok)─► verdict ─► END
              │                                   │                          │
              │(rc!=0, increments left)           │(not green)               │(fail, tries<2)
              └─► build (next increment)          └─► verdict                └─► repair ─► runnable_gate
              │(rc!=0, increments done)
              └─► repair ─►(green)─► integration_gate
                     │(still failing, under cap)
                     └─► repair
                     │(cap)
                     └─► verdict

The orchestration is the GRAPH (deterministic edges + exit-code gates). The LLM only acts INSIDE a
node: the architect plans (one direct model call in plan_node); the coder edits files (OpenCode,
driven in build_node/repair_node). Gates are exit codes, not opinions.

State vs. live handles — the LangGraph lesson here:
  * BuildState (TypedDict) holds only SERIALISABLE run progress (counters, last rc, flags). That is
    what a checkpointer could persist.
  * Live, non-serialisable handles — the OpenCode client, the running workspace container, the open
    trace — live OUTSIDE the graph in a RunContext that the node closures capture. You never put a
    socket or a container handle in graph state; this split is the real-world LangGraph pattern.
  * (Deviation from the handover's `cfg: dict` in state: config rides in RunContext alongside the
    other live handles, so all operational context sits in one place rather than half-in/half-out.)

    python3 -m harness.orchestrator --goal notes_api [--runtime kata]

Runs INSIDE the orchestrator container (docker/Dockerfile.orchestrator); see
scripts/run_orchestrator.sh for the mounts that let it reach OpenCode + spawn workspace containers.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

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


# ---- architect / plan (one direct model call) ----------------------------
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


# ---- graph state + live context ------------------------------------------
class BuildState(TypedDict):
    """SERIALISABLE run progress only — what a checkpointer could persist. Live handles (client,
    container, trace, config) live in RunContext, not here."""
    plan: list                  # [{name, description}] from the architect
    current_increment: int      # index of the next increment build_node will drive
    iteration: int              # 1-based count of OpenCode drives so far (build + repair)
    last_rc: int                # exit code of the most recent in-sandbox pytest run
    last_output: str            # tail of that run's stdout+stderr (fed forward to the next drive)
    integration_ok: bool        # full acceptance suite green
    runnable_ok: bool           # app actually launches + serves
    runnable_tries: int         # runnable-repair attempts spent
    verdict: str                # "done" | "not_done" (set by verdict_node)


class RunContext:
    """Non-serialisable, run-scoped handles the node closures share. Created once per run_goal,
    torn down in its finally — never placed in graph state."""

    def __init__(self, cfg: Config, goal: str, workspace: Path, run_cfg: dict,
                 trace: OrchestrationTrace, test_file: str):
        self.cfg = cfg
        self.goal = goal
        self.workspace = workspace          # host Path to the per-run workspace dir
        self.run_cfg = run_cfg
        self.trace = trace
        self.test_file = test_file
        self.client: OpenCodeClient | None = None
        self.session_id: str = ""
        self.ws: Workspace | None = None
        self.baseline: dict[str, str] = {}


# ---- verification (full acceptance suite, in the sandbox) ----------------
def _verify(ws: Workspace, workspace: Path):
    if (workspace / "requirements.txt").exists():
        return ws.exec("pip install -q -r requirements.txt && python -m pytest -q")
    return ws.exec("python -m pytest -q")


def _drive(ctx: RunContext, n: int, kind: str, instruction: str):
    """One build/repair drive: instruct the agent, snapshot the edit, verify in the sandbox,
    record an IterationTrace. Returns the ExecResult. Mirrors the old `_step`."""
    t0 = time.time()
    wsdir = str(ctx.workspace)
    usage = ctx.client.send_instruction(ctx.session_id, instruction, directory=wsdir,
                                        tools=AGENT_TOOLS)
    cur = _snapshot(ctx.workspace)
    touched = sorted(f for f, h in cur.items() if ctx.baseline.get(f) != h)
    result = _verify(ctx.ws, ctx.workspace)
    ctx.trace.add(IterationTrace(
        n=n, kind=kind, instruction=instruction, files_touched=touched,
        test_rc=result.rc, test_stdout_tail=_tail(result.stdout + result.stderr),
        failing_summary=_summarize_failures(result.stdout + result.stderr) if result.rc != 0 else "",
        tokens_in=usage.tokens_in, tokens_out=usage.tokens_out,
        tokens_reasoning=usage.tokens_reasoning, cost_usd=usage.cost_usd,
        wall_s=round(time.time() - t0, 3),
    ))
    ctx.baseline = cur
    return result


# ---- nodes (closures over ctx) -------------------------------------------
def build_graph(ctx: RunContext):
    cfg = ctx.cfg

    def plan_node(state: BuildState) -> dict:
        goal_md = (ctx.workspace / "GOAL.md").read_text()
        test_src = (ctx.workspace / ctx.test_file).read_text()
        plan = architect_plan(cfg, goal_md, test_src)
        ctx.trace.plan = plan
        print(f"[{ctx.goal}] PLAN ({len(plan)} increments):")
        for k, inc in enumerate(plan, 1):
            print(f"   {k}. {inc['name']}: {inc['description']}")
        return {"plan": plan}

    def build_node(state: BuildState) -> dict:
        idx = state["current_increment"]
        plan = state["plan"]
        if idx < len(plan):
            inc = plan[idx]
            label = inc["name"]
            instr = (
                f"Increment {idx + 1}: {inc['name']} — {inc['description']}\n"
                f"Work toward making `python -m pytest -q` pass for the WHOLE goal. Edit "
                f"`{ctx.run_cfg['stub']}` and `requirements.txt` as needed; do NOT edit "
                f"`{ctx.test_file}`. Add packages to requirements.txt (the harness installs them "
                f"in the sandbox)."
            )
            next_idx = idx + 1
        else:
            label = "continue"
            instr = (
                f"Continue working toward making `python -m pytest -q` pass for the whole goal. "
                f"Edit `{ctx.run_cfg['stub']}` and `requirements.txt`; do NOT edit `{ctx.test_file}`."
            )
            next_idx = idx
        if state["last_rc"] != 0 and state["last_output"]:
            instr += (f"\n\nThe current test run is FAILING — fix this as part of this step:\n"
                      f"```\n{_tail(state['last_output'])}\n```")
        n = state["iteration"] + 1
        result = _drive(ctx, n, f"build:{label}", instr)
        print(f"[{ctx.goal}] iter {n} build:{label}: pytest rc={result.rc}")
        return {"iteration": n, "current_increment": next_idx, "last_rc": result.rc,
                "last_output": result.stdout + result.stderr}

    def repair_node(state: BuildState) -> dict:
        # Two repair flavours, one node: a RUNNABLE repair once the suite is green but the app
        # won't serve, otherwise an ordinary TEST repair. Mode is derived from state, so the
        # router can re-derive it to pick which gate to revisit.
        n = state["iteration"] + 1
        if state["integration_ok"] and not state["runnable_ok"]:
            rc = ctx.run_cfg
            instr = (
                f"The app PASSES the tests but FAILS to launch as a server. Make `{rc['launch']}` "
                f"start and `{rc['probe']}` return {rc.get('expect_status', 200)}. Add any needed "
                f"package (e.g. uvicorn) to requirements.txt. Launch output:\n"
                f"```\n{ctx.trace.runnable_detail}\n```"
            )
            result = _drive(ctx, n, "runnable-repair", instr)
            print(f"[{ctx.goal}] iter {n} runnable-repair: pytest rc={result.rc}")
            return {"iteration": n, "last_rc": result.rc,
                    "last_output": result.stdout + result.stderr,
                    "runnable_tries": state["runnable_tries"] + 1}
        instr = repair_instruction(state["last_output"])
        result = _drive(ctx, n, "repair", instr)
        print(f"[{ctx.goal}] iter {n} repair: pytest rc={result.rc}")
        return {"iteration": n, "last_rc": result.rc,
                "last_output": result.stdout + result.stderr}

    def integration_gate_node(state: BuildState) -> dict:
        ok = state["last_rc"] == 0
        ctx.trace.integration_ok = ok
        if ok and ctx.trace.iterations_to_integration is None:
            ctx.trace.iterations_to_integration = state["iteration"]
        print(f"[{ctx.goal}] INTEGRATION gate: {'OK' if ok else 'FAIL'}")
        return {"integration_ok": ok}

    def runnable_gate_node(state: BuildState) -> dict:
        rc = ctx.run_cfg
        rg = ctx.ws.launch_and_probe(rc["launch"], rc["probe"], rc.get("expect_status", 200))
        ctx.trace.runnable_ok = rg.ok
        ctx.trace.runnable_detail = _tail(rg.stdout + rg.stderr)
        retry = f" (retry {state['runnable_tries']})" if state["runnable_tries"] else ""
        print(f"[{ctx.goal}] RUNNABLE gate{retry}: {'OK' if rg.ok else 'FAIL'}")
        return {"runnable_ok": rg.ok}

    def verdict_node(state: BuildState) -> dict:
        status = "done" if (state["integration_ok"] and state["runnable_ok"]) else "not_done"
        ctx.trace.finalize(status)
        return {"verdict": status}

    # ---- routers (pure functions of state) -------------------------------
    def build_router(state: BuildState) -> str:
        if state["last_rc"] == 0:
            return "integration_gate"
        if state["iteration"] >= cfg.max_iters:
            return "verdict"
        # PHASE-2 behaviour: keep building increments (carrying the failure forward) until they run
        # out, THEN fall back to PHASE-3 repair.
        if state["current_increment"] < len(state["plan"]):
            return "build"
        return "repair"

    def repair_router(state: BuildState) -> str:
        # A runnable repair just ran (suite already green, app not yet serving): re-probe.
        if state["integration_ok"] and not state["runnable_ok"]:
            return "runnable_gate"
        if state["last_rc"] == 0:
            return "integration_gate"
        if state["iteration"] < cfg.max_iters:
            return "repair"
        return "verdict"

    def integration_gate_router(state: BuildState) -> str:
        return "runnable_gate" if state["integration_ok"] else "verdict"

    def runnable_gate_router(state: BuildState) -> str:
        if state["runnable_ok"]:
            return "verdict"
        if state["runnable_tries"] < 2 and state["iteration"] < cfg.max_iters + 2:
            return "repair"
        return "verdict"

    g = StateGraph(BuildState)
    g.add_node("plan", plan_node)
    g.add_node("build", build_node)
    g.add_node("repair", repair_node)
    g.add_node("integration_gate", integration_gate_node)
    g.add_node("runnable_gate", runnable_gate_node)
    g.add_node("verdict", verdict_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "build")
    g.add_conditional_edges("build", build_router,
                            {"integration_gate": "integration_gate", "build": "build",
                             "repair": "repair", "verdict": "verdict"})
    g.add_conditional_edges("repair", repair_router,
                            {"runnable_gate": "runnable_gate", "integration_gate": "integration_gate",
                             "repair": "repair", "verdict": "verdict"})
    g.add_conditional_edges("integration_gate", integration_gate_router,
                            {"runnable_gate": "runnable_gate", "verdict": "verdict"})
    g.add_conditional_edges("runnable_gate", runnable_gate_router,
                            {"repair": "repair", "verdict": "verdict"})
    g.add_edge("verdict", END)
    return g.compile()


def run_goal(goal: str, cfg: Config) -> OrchestrationTrace:
    goal_dir = GOALS_DIR / goal
    run_cfg = json.loads((goal_dir / "run.json").read_text())
    test_file = run_cfg["test"]
    workspace = provision_goal(goal, cfg)
    wsdir = str(workspace)
    goal_md = (workspace / "GOAL.md").read_text()
    test_src = (workspace / test_file).read_text()

    trace = OrchestrationTrace(goal=goal, model=cfg.harness_model, runtime=cfg.runtime)
    ctx = RunContext(cfg=cfg, goal=goal, workspace=workspace, run_cfg=run_cfg,
                     trace=trace, test_file=test_file)

    client = OpenCodeClient(cfg.opencode_base_url, cfg.opencode_password,
                            cfg.opencode_provider_id, cfg.harness_model,
                            agent=cfg.opencode_agent or None)
    ctx.client = client
    try:
        ctx.session_id = client.create_session(directory=wsdir)
        client.send_context(
            ctx.session_id,
            f"# GOAL\n{goal_md}\n\n# Acceptance tests — do NOT edit `{test_file}`\n"
            f"```python\n{test_src}\n```\n",
            directory=wsdir,
        )

        ws = Workspace(workspace, cfg.workspace_image, runtime=cfg.runtime)
        ws.start()
        ctx.ws = ws
        ctx.baseline = _snapshot(workspace)

        graph = build_graph(ctx)
        init: BuildState = {
            "plan": [], "current_increment": 0, "iteration": 0, "last_rc": 1,
            "last_output": "", "integration_ok": False, "runnable_ok": False,
            "runnable_tries": 0, "verdict": "",
        }
        # recursion_limit caps total node visits; the per-phase caps (max_iters, runnable_tries)
        # are the real bounds — this just guards against a router bug looping forever.
        graph.invoke(init, config={"recursion_limit": 50})
        # verdict_node already finalized the trace on a normal finish.
    except OpenCodeError as e:
        trace.finalize("error", f"OpenCode: {e}")
    except Exception as e:  # noqa: BLE001 — record any failure into the trace
        trace.finalize("error", repr(e))
    finally:
        if ctx.ws is not None:
            ctx.ws.stop()
        client.close()

    out = trace.save(TRACES_DIR)
    print(f"[{goal}] VERDICT={trace.final_status} integration={trace.integration_ok} "
          f"runnable={trace.runnable_ok} iters={len(trace.iterations)} -> {out}")
    return trace


def main(argv: list[str] | None = None) -> int:
    goals = available_goals()
    ap = argparse.ArgumentParser(description="poc-builder-prework outer orchestration loop (LangGraph)")
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
