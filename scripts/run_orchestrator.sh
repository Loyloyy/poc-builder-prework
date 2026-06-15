#!/usr/bin/env bash
# Build the orchestrator image and run the LangGraph OUTER loop INSIDE a container.
#
# Why a container: the harness host is stdlib-only (CLAUDE.md #4 — no host pip/venv); LangGraph
# lives in this image instead. The mounts below let it act as if it were on the host:
#   --network host          -> OpenCode on 127.0.0.1:<port> is the host's own localhost
#   -v docker.sock          -> harness/runtime.py spawns WORKSPACE containers via the host daemon
#   -v $WS_ROOT:$WS_ROOT     -> workspace root at the SAME absolute path inside & out, so the bind
#                              mounts this process hands to `docker run` resolve on the host, and
#                              OpenCode (host process) edits the very same files
#   -v repo:/app            -> run the authored code + write traces/ back to the host
#
# Precondition: `opencode serve` is already running on the host (see runbooks); .env is filled in
# at the repo root. Usage:
#   HARNESS_WORKSPACE_ROOT=/var/tmp/stage3-ws ./scripts/run_orchestrator.sh [goal] [docker|kata]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GOAL="${1:-notes_api}"
RUNTIME="${2:-${HARNESS_RUNTIME:-docker}}"
IMAGE="poc-prework-orchestrator:latest"

# The workspace root MUST be an absolute host path and is mounted at the IDENTICAL path inside the
# container — otherwise the bind mounts the orchestrator hands to the host daemon point at nothing.
WS_ROOT="${HARNESS_WORKSPACE_ROOT:?set HARNESS_WORKSPACE_ROOT to an ABSOLUTE host path (e.g. /var/tmp/stage3-ws)}"
case "$WS_ROOT" in
  /*) ;;
  *) echo "HARNESS_WORKSPACE_ROOT must be an ABSOLUTE path, got: $WS_ROOT" >&2; exit 1 ;;
esac
mkdir -p "$WS_ROOT"

echo "Building $IMAGE ..."
docker build -t "$IMAGE" -f "$REPO_ROOT/docker/Dockerfile.orchestrator" "$REPO_ROOT"

echo "Running orchestrator (goal=$GOAL runtime=$RUNTIME ws_root=$WS_ROOT) ..."
docker run --rm \
  --network host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$WS_ROOT":"$WS_ROOT" \
  -v "$REPO_ROOT":/app \
  -e HARNESS_WORKSPACE_ROOT="$WS_ROOT" \
  -e HARNESS_RUNTIME="$RUNTIME" \
  "$IMAGE" \
  python -m harness.orchestrator --goal "$GOAL" --runtime "$RUNTIME"
