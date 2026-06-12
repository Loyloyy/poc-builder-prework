"""Structured, machine-readable run traces.

One JSON file per harness run under traces/. Deliberately flat and explicit so Phase 4
can answer concretely: "could these traces feed Hermes' evolution loop, and what adapter
would that require?" (see runbooks/PHASE4_HERMES.md). Keep field names stable."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class IterationTrace:
    n: int                          # 1-based iteration index
    kind: str                       # "build" (first) | "repair"
    instruction: str               # exact instruction sent to OpenCode this iteration
    files_touched: list[str] = field(default_factory=list)
    test_rc: int | None = None      # pytest exit code (0 == green)
    test_stdout_tail: str = ""      # last lines of pytest output (truncated)
    failing_summary: str = ""       # short human summary of failures fed into the next repair
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    wall_s: float = 0.0


@dataclass
class RunTrace:
    task: str                       # "t1" | "t2"
    model: str                      # HARNESS_MODEL as used (frontier vs vLLM is visible here)
    runtime: str                    # "docker" | "kata"
    started_at: float = field(default_factory=time.time)
    iterations: list[IterationTrace] = field(default_factory=list)
    final_status: str = "unknown"   # "green" | "cap_reached" | "spend_cap" | "error"
    error: str = ""

    # ---- derived totals (filled by finalize) ----
    iterations_to_pass: int | None = None
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    total_wall_s: float = 0.0

    def add(self, it: IterationTrace) -> None:
        self.iterations.append(it)

    def finalize(self, status: str, error: str = "") -> None:
        self.final_status = status
        self.error = error
        self.total_tokens_in = sum(i.tokens_in for i in self.iterations)
        self.total_tokens_out = sum(i.tokens_out for i in self.iterations)
        self.total_cost_usd = round(sum(i.cost_usd for i in self.iterations), 6)
        self.total_wall_s = round(sum(i.wall_s for i in self.iterations), 3)
        if status == "green" and self.iterations:
            self.iterations_to_pass = self.iterations[-1].n

    def save(self, traces_dir: Path) -> Path:
        traces_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(self.started_at))
        out = traces_dir / f"{self.task}_{self.runtime}_{stamp}.json"
        out.write_text(json.dumps(asdict(self), indent=2))
        return out
