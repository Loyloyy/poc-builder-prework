# Goal: Notes REST API

Build a small FastAPI service (an app object named `app`) for managing text notes. An in-memory
store (a dict) is fine — no database.

## Endpoints
- `GET /health` → `200`, JSON `{"status": "ok"}`
- `POST /notes` with JSON `{"text": "<string>"}` → `201`, JSON `{"id": <id>, "text": "<text>"}`.
  A body missing `text` → `422`.
- `GET /notes` → `200`, a JSON list of all notes.
- `GET /notes/{id}` → `200` the note, or `404` if it doesn't exist.
- `DELETE /notes/{id}` → `204` (no body); afterwards that note is `404`.

## Definition of Done
- `python -m pytest -q` passes (the acceptance tests).
- The app LAUNCHES as a server: `uvicorn app:app` starts and `GET /health` returns 200.

Put dependencies in `requirements.txt` (the harness installs them in the sandbox). Keep it minimal.
