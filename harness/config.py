"""Env-driven configuration. No model names, hosts, or keys are hardcoded — all come
from the gitignored .env (see .env.example). Load order: process env wins; we do a
minimal .env parse so scripts work without python-dotenv installed."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (no dependency). Does not override already-set process env."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


# Look for .env next to the repo root (parent of this package).
_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _req(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val or val.startswith("<"):
        raise SystemExit(
            f"[config] {name} is not set (or still a <placeholder>). "
            f"Copy .env.example -> .env and fill it in on the server."
        )
    return val


@dataclass(frozen=True)
class Config:
    # Model endpoint — a DIRECT OpenAI-compatible endpoint (self-hosted vLLM, or a frontier
    # provider's OpenAI-compatible API / OpenRouter). No proxy in between.
    model_api_base: str
    model_api_key: str
    harness_model: str
    opencode_provider_id: str

    # OpenCode headless server
    opencode_host: str
    opencode_port: int
    opencode_password: str

    # Harness loop
    max_iters: int
    spend_cap_usd: float
    runtime: str            # "docker" | "kata"
    workspace_root: Path
    workspace_image: str

    @property
    def opencode_base_url(self) -> str:
        return f"http://{self.opencode_host}:{self.opencode_port}"


def load_config() -> Config:
    runtime = os.environ.get("HARNESS_RUNTIME", "docker").strip().lower()
    if runtime not in {"docker", "kata"}:
        raise SystemExit(f"[config] HARNESS_RUNTIME must be 'docker' or 'kata', got {runtime!r}")
    return Config(
        model_api_base=_req("MODEL_API_BASE"),
        model_api_key=_req("MODEL_API_KEY"),
        harness_model=_req("HARNESS_MODEL"),
        opencode_provider_id=os.environ.get("OPENCODE_PROVIDER_ID", "local").strip(),
        opencode_host=os.environ.get("OPENCODE_HOST", "127.0.0.1").strip(),
        opencode_port=int(os.environ.get("OPENCODE_PORT", "4096")),
        opencode_password=_req("OPENCODE_SERVER_PASSWORD"),
        max_iters=int(os.environ.get("HARNESS_MAX_ITERS", "4")),
        spend_cap_usd=float(os.environ.get("HARNESS_SPEND_CAP_USD", "2.00")),
        runtime=runtime,
        workspace_root=Path(os.path.expanduser(
            os.environ.get("HARNESS_WORKSPACE_ROOT", "~/stage3-prework/workspaces"))),
        workspace_image=os.environ.get("HARNESS_WORKSPACE_IMAGE", "poc-prework-workspace:latest"),
    )
