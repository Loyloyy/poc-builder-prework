#!/usr/bin/env bash
# Manual helper to launch a workspace container the same way harness/runtime.py does — handy
# for poking at a task by hand. Honours RUNTIME=docker|kata.
#
#   ./docker/run-workspace.sh /abs/path/to/workspace [image]
#
# Then: docker exec -it <name> bash ; inside: python -m pytest -q
set -euo pipefail

WORKDIR="${1:?usage: run-workspace.sh <workspace-dir> [image]}"
IMAGE="${2:-poc-prework-workspace:latest}"
RUNTIME="${RUNTIME:-docker}"
NAME="poc-prework-manual-$(date +%s)"

RUNTIME_FLAG=()
if [[ "$RUNTIME" == "kata" ]]; then
  # VERIFY the registered runtime name: `docker info | grep -iA3 runtimes`
  RUNTIME_FLAG=(--runtime io.containerd.kata.v2)
fi

echo "Building workspace image ($IMAGE) if needed..."
docker build -t "$IMAGE" -f "$(dirname "$0")/Dockerfile.workspace" "$(dirname "$0")"

echo "Starting $NAME (runtime=$RUNTIME) on $WORKDIR ..."
docker run -d --rm --name "$NAME" "${RUNTIME_FLAG[@]}" \
  -v "$(realpath "$WORKDIR")":/work -w /work "$IMAGE" sleep infinity

echo "Container up: $NAME"
echo "  shell : docker exec -it $NAME bash"
echo "  test  : docker exec $NAME python -m pytest -q"
echo "  stop  : docker rm -f $NAME"
