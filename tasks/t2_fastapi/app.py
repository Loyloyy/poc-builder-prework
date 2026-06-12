"""Task T2 stub — the agent must implement this.

The import below is deliberately WRONG (`FastApi` is not a symbol in fastapi). This is an
induced failure so the harness must run at least one repair iteration to recover. The agent
should fix the import and implement GET /health -> 200 {"status": "ok"}."""

from fastapi import FastApi  # noqa: F401  <-- WRONG ON PURPOSE; should be `FastAPI`

# TODO(agent): create `app` and add the /health route.
