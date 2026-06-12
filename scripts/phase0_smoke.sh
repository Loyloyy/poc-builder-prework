#!/usr/bin/env bash
# Phase 0 — install OpenCode, start the headless server, save /doc as ground truth, and
# prove the model endpoint answers (direct OpenAI-compatible, no proxy). Run on the SERVER.
#
# Success: server answers over HTTP, docs/openapi.json saved, model endpoint returns a completion.
#
# ⚠️  Commands/package names reflect early-2026 knowledge — VERIFY each before trusting it
#     (installed --version, official docs). Tell the user where reality differed.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env (MODEL_*, OPENCODE_*).
set -a; [[ -f .env ]] && . ./.env; set +a
: "${OPENCODE_PORT:=4096}" "${OPENCODE_HOST:=127.0.0.1}"

echo "== 1. Install OpenCode (VERIFY current install method vs docs) =="
# Common channels — pick whatever is current; do not assume:
#   curl -fsSL https://opencode.ai/install | bash      # official installer
#   npm i -g opencode-ai                                # npm
command -v opencode >/dev/null || echo "  opencode not found — install it, then re-run."
opencode --version || true

echo "== 2. Start headless server (background) =="
: "${OPENCODE_SERVER_PASSWORD:?set OPENCODE_SERVER_PASSWORD in .env}"
# VERIFY the flag names: `opencode serve --help`. Some builds use --hostname/--port.
OPENCODE_SERVER_PASSWORD="$OPENCODE_SERVER_PASSWORD" \
  opencode serve --port "$OPENCODE_PORT" >/tmp/opencode-serve.log 2>&1 &
SERVE_PID=$!
echo "  serve pid=$SERVE_PID (log: /tmp/opencode-serve.log)"
sleep 3

echo "== 3. Fetch /doc -> docs/openapi.json (GROUND TRUTH for the client) =="
curl -fsS "http://${OPENCODE_HOST}:${OPENCODE_PORT}/doc" -o docs/openapi.json \
  && echo "  saved docs/openapi.json ($(wc -c < docs/openapi.json) bytes)" \
  || { echo "  /doc fetch FAILED — check the log and the auth scheme."; }

echo "== 4. Prove the model endpoint answers (trivial non-coding completion, DIRECT) =="
: "${MODEL_API_BASE:?}" "${MODEL_API_KEY:?}" "${HARNESS_MODEL:?}"
curl -fsS "${MODEL_API_BASE%/}/chat/completions" \
  -H "Authorization: Bearer ${MODEL_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${HARNESS_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"reply with the single word: pong\"}],\"max_tokens\":5}" \
  && echo "" && echo "  model endpoint OK" \
  || echo "  model call FAILED — check base url / key / model id."

echo
echo "Phase 0 done. Next: python scripts/verify_openapi.py  (reconcile client vs /doc)."
echo "Leave the server running for Phases 1-2, or: kill $SERVE_PID"
