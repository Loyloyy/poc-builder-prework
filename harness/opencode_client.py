"""HTTP client for driving OpenCode headlessly (the `opencode serve` server).

Reconciled against the LIVE /doc of OpenCode 1.15.13 (saved at docs/openapi.json). Key facts:
  * Session create (POST /session): body {model:{id, providerID}, agent?}; the working dir is
    a QUERY param `?directory=<abs>` (NOT a body field — body has additionalProperties:false).
  * Send (POST /session/{sessionID}/message) is SYNCHRONOUS — it blocks and returns the
    completed assistant turn {info, parts}, with info.tokens {input,output,...} + info.cost +
    info.error?. No polling needed. Body: {parts:[{type:"text",text}], noReply?:bool}.
    (model is inherited from the session; per-message model would use {providerID, modelID}.)
  * `noReply: true` injects context without driving a full reply.

If a future OpenCode changes this, re-run scripts/verify_openapi.py and the schema dump in the
README, then adjust the EP table + bodies below.
"""

from __future__ import annotations

import json as _json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# Stdlib-only on purpose: the harness host needs ZERO pip installs (no httpx, no venv).


# ---------------------------------------------------------------------------
# ENDPOINT TABLE — the place to edit if /doc disagrees. {sessionID} is substituted.
# ---------------------------------------------------------------------------
class EP:
    DOC = "/doc"                                       # OpenAPI spec (ground truth)
    SESSION = "/session"                               # POST create, GET list
    MESSAGE = "/session/{sessionID}/message"           # POST send (synchronous), GET list
    ABORT = "/session/{sessionID}/abort"               # POST cancel (best effort)


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_reasoning: int = 0    # reasoning models (e.g. GLM) put most output here
    cost_usd: float = 0.0


class OpenCodeError(RuntimeError):
    pass


class OpenCodeClient:
    def __init__(self, base_url: str, password: str, provider_id: str, model: str,
                 agent: str | None = None, timeout_s: float = 600.0):
        self._base = base_url.rstrip("/")
        self._provider_id = provider_id
        self._model = model
        self._agent = agent or None
        self._timeout = timeout_s
        # A normal loopback `opencode serve` needs no auth; headers carry a password only if set.
        self._headers = {"Content-Type": "application/json"}
        if password:
            self._headers["Authorization"] = f"Bearer {password}"
            self._headers["x-opencode-password"] = password

    def close(self) -> None:
        pass  # urllib opens per-request

    def __enter__(self) -> "OpenCodeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- low-level (stdlib urllib) --------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None,
                 query: dict | None = None) -> dict | list:
        url = self._base + path
        if query:
            qs = urllib.parse.urlencode({k: v for k, v in query.items() if v})
            if qs:
                url += "?" + qs
        data = _json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise OpenCodeError(
                f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')[:600]}")
        except urllib.error.URLError as e:
            raise OpenCodeError(f"{method} {path} -> connection error: {e.reason}")
        return _json.loads(raw) if raw else {}

    # ---- ops the harness relies on --------------------------------------
    def health(self) -> dict:
        spec = self._request("GET", EP.DOC)
        info = spec.get("info", {}) if isinstance(spec, dict) else {}
        return {"ok": True, "title": info.get("title"), "version": info.get("version")}

    def fetch_openapi(self) -> dict:
        spec = self._request("GET", EP.DOC)
        if not isinstance(spec, dict):
            raise OpenCodeError("/doc did not return a JSON object")
        return spec

    def create_session(self, directory: str | None = None) -> str:
        """Create a session bound to our model (+ optional scoped agent), scoped to `directory`
        via ?directory= so the agent operates on the per-run workspace."""
        body: dict = {"model": {"id": self._model, "providerID": self._provider_id}}
        if self._agent:
            body["agent"] = self._agent
        data = self._request("POST", EP.SESSION, body=body, query={"directory": directory})
        sid = data.get("id") if isinstance(data, dict) else None
        if not sid:
            raise OpenCodeError(f"no session id in create response: {data!r}")
        return sid

    def send_context(self, sid: str, context: str, directory: str | None = None) -> None:
        """Inject reference material WITHOUT driving a build (noReply=true). Best-effort: the
        agent can also read the files directly from the workspace, so this is a convenience."""
        try:
            self._send(sid, context, directory=directory, no_reply=True)
        except OpenCodeError:
            pass

    def send_instruction(self, sid: str, instruction: str, directory: str | None = None,
                         tools: dict | None = None) -> Usage:
        """Send a build/repair instruction. The POST blocks until the turn completes and returns
        the assistant message; we surface its token/cost usage and raise on a turn error.
        `tools` (e.g. {"bash": False}) disables OpenCode tools for this turn — important because
        OpenCode's bash runs on the SERVE HOST, not in our container; for file-only tasks we keep
        the agent to edits and let the harness verify in the container."""
        resp = self._send(sid, instruction, directory=directory, no_reply=False, tools=tools)
        info = resp.get("info", {}) if isinstance(resp, dict) else {}
        if info.get("error"):
            raise OpenCodeError(f"assistant turn errored: {_json.dumps(info['error'])[:400]}")
        return _usage(info)

    def abort(self, sid: str) -> None:
        try:
            self._request("POST", EP.ABORT.format(sessionID=sid))
        except OpenCodeError:
            pass

    # ---- internals -------------------------------------------------------
    def _send(self, sid: str, text: str, directory: str | None = None,
              no_reply: bool = False, tools: dict | None = None) -> dict:
        body: dict = {"parts": [{"type": "text", "text": text}]}
        if no_reply:
            body["noReply"] = True
        if tools:
            body["tools"] = tools
        out = self._request("POST", EP.MESSAGE.format(sessionID=sid),
                            body=body, query={"directory": directory})
        return out if isinstance(out, dict) else {}


def _usage(info: dict) -> Usage:
    t = info.get("tokens", {}) or {}
    return Usage(
        tokens_in=int(t.get("input", 0) or 0),
        tokens_out=int(t.get("output", 0) or 0),
        tokens_reasoning=int(t.get("reasoning", 0) or 0),
        cost_usd=float(info.get("cost", 0.0) or 0.0),
    )
