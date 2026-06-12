"""HTTP client for driving OpenCode headlessly (the `opencode serve` server).

╔══════════════════════════════════════════════════════════════════════════════════╗
║  ⚠️  VERIFY AGAINST  GET /doc  BEFORE TRUSTING ANYTHING IN THIS FILE.            ║
║                                                                                  ║
║  Every endpoint path and payload shape below is written from early-2026          ║
║  knowledge of OpenCode and WILL drift. The running server's OpenAPI spec at      ║
║  GET /doc is the ground truth. Run `python scripts/verify_openapi.py` first; it  ║
║  diffs the EP constants here against the live spec and tells you what to fix.    ║
║                                                                                  ║
║  When reality differs: change ONLY the EP table + the (un)wrap helpers below.    ║
║  The rest of the harness depends on this module's method contract, not on paths. ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


# ---------------------------------------------------------------------------
# ENDPOINT TABLE — the ONLY place to edit when /doc disagrees. {sid} = session id.
# ---------------------------------------------------------------------------
class EP:
    DOC = "/doc"                              # OpenAPI spec (ground truth)
    SESSION_CREATE = "/session"              # POST -> {"id": ...}
    SESSION_LIST = "/session"               # GET
    MESSAGE_SEND = "/session/{sid}/message"  # POST a prompt (parts + provider/model)
    MESSAGE_LIST = "/session/{sid}/message"  # GET conversation (assistant replies, usage)
    SESSION_ABORT = "/session/{sid}/abort"   # POST cancel an in-flight run (best effort)


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class OpenCodeError(RuntimeError):
    pass


class OpenCodeClient:
    """Thin wrapper. Auth via the server password (header below — VERIFY the scheme:
    some builds use Authorization: Bearer, others a custom header or basic auth)."""

    def __init__(self, base_url: str, password: str, provider_id: str, model: str,
                 timeout_s: float = 300.0):
        self._provider_id = provider_id
        self._model = model
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={
                # VERIFY: header name/scheme for OPENCODE_SERVER_PASSWORD against /doc.
                # We send both common variants; harmless if one is ignored.
                "Authorization": f"Bearer {password}",
                "x-opencode-password": password,
            },
        )

    # ---- lifecycle -------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OpenCodeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- low-level -------------------------------------------------------
    def _post(self, path: str, json: dict | None = None) -> dict:
        r = self._http.post(path, json=json or {})
        if r.status_code >= 400:
            raise OpenCodeError(f"POST {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else {}

    def _get(self, path: str) -> dict | list:
        r = self._http.get(path)
        if r.status_code >= 400:
            raise OpenCodeError(f"GET {path} -> {r.status_code}: {r.text[:500]}")
        return r.json()

    # ---- ops the harness relies on --------------------------------------
    def health(self) -> dict:
        """Server reachable + OpenAPI present. Returns minimal info from /doc."""
        spec = self._get(EP.DOC)
        info = spec.get("info", {}) if isinstance(spec, dict) else {}
        return {"ok": True, "openapi_title": info.get("title"), "version": info.get("version")}

    def fetch_openapi(self) -> dict:
        spec = self._get(EP.DOC)
        if not isinstance(spec, dict):
            raise OpenCodeError("/doc did not return a JSON object")
        return spec

    def create_session(self, title: str = "poc-prework", directory: str | None = None) -> str:
        # VERIFY: body keys + id field name. `directory` ties the session to the per-run
        # workspace so the agent edits THERE (the key may be "directory"/"path"/"cwd"). If the
        # server ignores it, start `opencode serve` with the workspace as its cwd instead.
        body: dict = {"title": title}
        if directory:
            body["directory"] = directory
        data = self._post(EP.SESSION_CREATE, body)
        sid = data.get("id") or data.get("sessionID") or data.get("session", {}).get("id")
        if not sid:
            raise OpenCodeError(f"could not find session id in create response: {data!r}")
        return sid

    def send_context(self, sid: str, context: str) -> None:
        """Inject reference context that should NOT trigger a build action — a 'no-reply'
        framing. OpenCode has no true no-reply, so we prefix an instruction telling the
        model to acknowledge only. The build instruction comes next via send_instruction."""
        self._send(sid, (
            "CONTEXT ONLY — do not edit files or run commands yet. "
            "Acknowledge in one word. Here is the reference material:\n\n" + context
        ))

    def send_instruction(self, sid: str, instruction: str) -> Usage:
        """Send a build/repair instruction and block until the assistant turn completes.
        Returns token/cost usage for THIS turn (best-effort parse)."""
        before = self._message_count(sid)
        self._send(sid, instruction)
        return self._await_turn(sid, since_count=before)

    def abort(self, sid: str) -> None:
        try:
            self._post(EP.SESSION_ABORT.format(sid=sid))
        except OpenCodeError:
            pass  # best effort

    # ---- internals -------------------------------------------------------
    def _send(self, sid: str, text: str) -> None:
        # VERIFY: the message body schema. Common OpenCode shape is a parts array plus
        # explicit provider/model routing. Adjust keys here to match /doc.
        body = {
            "providerID": self._provider_id,
            "modelID": self._model,
            "parts": [{"type": "text", "text": text}],
        }
        self._post(EP.MESSAGE_SEND.format(sid=sid), body)

    def _messages(self, sid: str) -> list:
        data = self._get(EP.MESSAGE_LIST.format(sid=sid))
        if isinstance(data, dict):
            data = data.get("messages") or data.get("data") or []
        return data if isinstance(data, list) else []

    def _message_count(self, sid: str) -> int:
        return len(self._messages(sid))

    def _await_turn(self, sid: str, since_count: int, poll_s: float = 2.0,
                    max_wait_s: float = 600.0) -> Usage:
        """Poll until a new assistant message appears AND it is no longer streaming.

        VERIFY: how completion is signalled. Candidates seen in the wild: a `time.completed`
        timestamp on the assistant message, a `status`/`finishReason` field, or the SSE
        /event stream. Polling the message list is the most version-robust; swap to SSE if
        /doc exposes it cleanly. We treat 'a new assistant message with usage present and
        no streaming flag' as done."""
        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            msgs = self._messages(sid)
            new = msgs[since_count:]
            assistant = [m for m in new if _role(m) == "assistant"]
            done = [m for m in assistant if _turn_complete(m)]
            if done:
                return _parse_usage(done[-1])
            time.sleep(poll_s)
        raise OpenCodeError(f"timed out after {max_wait_s}s waiting for assistant turn on {sid}")


# ---- response-shape helpers (also VERIFY against /doc) ---------------------
def _role(msg: dict) -> str:
    return (msg.get("role") or msg.get("info", {}).get("role") or "").lower()


def _turn_complete(msg: dict) -> bool:
    info = msg.get("info", msg)
    if info.get("finishReason") or info.get("finish_reason"):
        return True
    t = info.get("time") or {}
    if isinstance(t, dict) and t.get("completed"):
        return True
    if info.get("status") in {"completed", "done", "idle"}:
        return True
    # Fall back: presence of usage usually means the turn closed.
    return bool(_raw_usage(info))


def _raw_usage(msg: dict) -> dict:
    info = msg.get("info", msg)
    return info.get("usage") or info.get("tokens") or {}


def _parse_usage(msg: dict) -> Usage:
    u = _raw_usage(msg)
    tin = int(u.get("input") or u.get("prompt_tokens") or u.get("input_tokens") or 0)
    tout = int(u.get("output") or u.get("completion_tokens") or u.get("output_tokens") or 0)
    cost = float(u.get("cost") or (msg.get("info", msg).get("cost")) or 0.0)
    return Usage(tokens_in=tin, tokens_out=tout, cost_usd=cost)
