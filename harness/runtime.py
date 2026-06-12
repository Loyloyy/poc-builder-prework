"""Container runtime helpers. The build engine executes arbitrary code, so verification
ALWAYS runs in a container, never on the host.

Phase 1-2: runtime="docker" (default runc).
Phase 3  : runtime="kata"  -> adds `--runtime io.containerd.kata.v2` (VERIFY the exact
           runtime name your install registered: `docker info | grep -i runtime`, or
           `--runtime kata-runtime` on older setups). This is the ONLY phase-3 change.

The workspace container is started detached and kept alive; we `docker exec` into it for
each verification so the agent's edits (made via OpenCode against a bind-mounted dir) are
seen immediately. Egress is dropped (`--network none`) per the guardrails; the agent's
own package installs happen against a wheels cache or a one-shot online build — see
docker/Dockerfile.workspace and the Phase-2 notes in README."""

from __future__ import annotations

import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecResult:
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


def _runtime_flag(runtime: str) -> list[str]:
    if runtime == "kata":
        # The runtime NAME as registered in /etc/docker/daemon.json (a named runtime, so the
        # daemon's DEFAULT runtime is untouched). On this server that's "kata"; VERIFY with
        # `docker info | grep -iA3 runtimes`.
        return ["--runtime", "kata"]
    return []  # docker default (runc)


class Workspace:
    """A throwaway, container-backed workspace for one task run."""

    def __init__(self, host_dir: Path, image: str, runtime: str = "docker",
                 allow_egress_for_install: bool = True):
        self.host_dir = host_dir.resolve()
        self.image = image
        self.runtime = runtime
        # Phase 2 needs the agent to `pip install`; to honour "deny egress" strictly,
        # pre-bake wheels in the image and run --network none. Set False once that's done.
        self.allow_egress_for_install = allow_egress_for_install
        self.name = f"poc-prework-{uuid.uuid4().hex[:8]}"
        self._started = False

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        net = [] if self.allow_egress_for_install else ["--network", "none"]
        cmd = [
            "docker", "run", "-d", "--rm",
            "--name", self.name,
            *_runtime_flag(self.runtime),
            *net,
            "-v", f"{self.host_dir}:/work",
            "-w", "/work",
            self.image,
            "sleep", "infinity",
        ]
        _run(cmd, check=True)
        self._started = True

    def stop(self) -> None:
        if self._started:
            _run(["docker", "rm", "-f", self.name], check=False)
            self._started = False

    def __enter__(self) -> "Workspace":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---- exec ------------------------------------------------------------
    def exec(self, shell_cmd: str, timeout_s: int = 600) -> ExecResult:
        """Run a shell command inside the workspace container."""
        cmd = ["docker", "exec", self.name, "bash", "-lc", shell_cmd]
        return _run(cmd, check=False, timeout_s=timeout_s)

    def run_pytest(self, timeout_s: int = 600) -> ExecResult:
        """Verification gate. Exit 0 == green."""
        return self.exec("python -m pytest -q", timeout_s=timeout_s)

    def copy_in(self, host_path: str, container_path: str) -> None:
        """Copy a host file into the running container. Used to inject hidden tests at verify time
        OUTSIDE /work, so the agent never sees them via the bind mount."""
        _run(["docker", "cp", host_path, f"{self.name}:{container_path}"], check=True)


def _run(cmd: list[str], check: bool, timeout_s: int = 600) -> ExecResult:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        return ExecResult(rc=124, stdout=e.stdout or "", stderr=f"timeout after {timeout_s}s")
    res = ExecResult(rc=p.returncode, stdout=p.stdout, stderr=p.stderr)
    if check and not res.ok:
        raise RuntimeError(f"command failed ({res.rc}): {shlex.join(cmd)}\n{res.stderr[:500]}")
    return res
