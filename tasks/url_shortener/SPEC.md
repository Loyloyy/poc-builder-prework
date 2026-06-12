Build a minimal URL shortener in `app.py` — a FastAPI app object named `app`. An in-memory
store (a dict) is fine; no database.

Endpoints:
- `POST /shorten` with JSON body `{"url": "<string>"}` → `200`, JSON `{"code": "<short code>",
  "short_url": "<full short url containing the code>"}`. A request body missing `url` must be
  rejected with `422`.
- `GET /{code}` → `307` redirect to the stored URL (the `Location` header must equal the
  original URL exactly). An unknown code → `404`.

Add dependencies to `requirements.txt` (the harness installs them in the sandbox). Make
`python -m pytest -q` pass. Keep it minimal.
