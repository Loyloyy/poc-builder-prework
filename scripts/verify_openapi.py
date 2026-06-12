"""Reconcile the OpenCode client's assumed endpoints against the LIVE /doc spec.

Run this AFTER phase0_smoke.sh and BEFORE the harness. It fetches the server's OpenAPI spec
and reports which paths the client assumes exist vs. what the server actually exposes — so
API drift is caught explicitly instead of failing deep inside a run.

    python scripts/verify_openapi.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config            # noqa: E402
from harness.opencode_client import EP, OpenCodeClient  # noqa: E402


def assumed_paths() -> list[str]:
    # Normalise {sid} -> a path-template form for comparison with the spec's path keys.
    out = []
    for name in dir(EP):
        if name.isupper():
            val = getattr(EP, name)
            out.append(re.sub(r"\{sid\}", "{id}", val))
    return sorted(set(out))


def main() -> int:
    cfg = load_config()
    client = OpenCodeClient(cfg.opencode_base_url, cfg.opencode_password,
                            cfg.opencode_provider_id, cfg.harness_model)
    try:
        spec = client.fetch_openapi()
    finally:
        client.close()

    server_paths = set((spec.get("paths") or {}).keys())
    print(f"Server exposes {len(server_paths)} paths. Title: "
          f"{spec.get('info', {}).get('title')} v{spec.get('info', {}).get('version')}\n")

    def matches(assumed: str) -> bool:
        # Treat differing param names as a match (e.g. {id} vs {sessionID}).
        pat = "^" + re.sub(r"\{[^}]+\}", r"\\{[^}]+\\}", re.escape(assumed)
                           .replace(r"\{id\}", "{id}")) + "$"
        pat = pat.replace("{id}", r"\{[^}]+\}")
        return any(re.match(pat, sp) for sp in server_paths)

    ok = True
    for a in assumed_paths():
        hit = a in server_paths or matches(a)
        print(f"  [{'OK ' if hit else 'MISS'}] {a}")
        ok = ok and hit

    if not ok:
        print("\n⚠️  Some assumed paths are missing. Edit the EP table + (un)wrap helpers in "
              "harness/opencode_client.py to match the spec above. Inspect with:\n"
              "    python -c \"import json;print('\\n'.join(json.load(open('docs/openapi.json'))['paths']))\"")
    else:
        print("\nAll assumed endpoints are present. Client paths look consistent with /doc.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
