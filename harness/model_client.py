"""Direct OpenAI-compatible chat call (stdlib urllib) for the ARCHITECT/planning role — kept
separate from the coder (OpenCode), which edits files. Reuses the same model endpoint config.
This is the 'plan' step's only LLM use; everything else flows through OpenCode."""

from __future__ import annotations

import json as _json
import urllib.error
import urllib.request

from .config import Config


def chat(cfg: Config, prompt: str, system: str | None = None, max_tokens: int = 2000) -> str:
    """One non-streaming chat completion against MODEL_API_BASE. Returns the assistant text
    (falls back to a `reasoning` field if a reasoning model leaves `content` empty)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": cfg.harness_model, "messages": messages,
            "max_tokens": max_tokens, "temperature": 0.2}
    req = urllib.request.Request(
        cfg.model_api_base.rstrip("/") + "/chat/completions",
        data=_json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg.model_api_key}"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        data = _json.loads(r.read())
    msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
    return msg.get("content") or msg.get("reasoning") or ""
