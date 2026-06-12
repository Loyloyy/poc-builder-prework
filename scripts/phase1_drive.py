"""Phase 1 — drive OpenCode headlessly ONCE on Task T1 (no repair loop). This is the
Phase-1 gate: the agent edits the stub and `pytest` exits 0 on the first build.

    python scripts/phase1_drive.py

It reuses the harness building blocks but caps iterations at 1, so a single build either
passes or it doesn't (no repair). Captures files changed, wall-clock, tokens/cost via the
saved trace. For the full repair loop, use `python -m harness.harness --task t1`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import Config, load_config  # noqa: E402
from harness.harness import run_task             # noqa: E402


def main() -> int:
    cfg = load_config()
    cfg = Config(**{**cfg.__dict__, "max_iters": 1})  # single build, no repair
    trace = run_task("t1", cfg)
    print("\nPhase 1 gate:", "PASS" if trace.final_status == "green" else "FAIL")
    return 0 if trace.final_status == "green" else 1


if __name__ == "__main__":
    sys.exit(main())
