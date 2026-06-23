# AGENTS.md

## Cursor Cloud specific instructions

Nutrition Tracker is a single FastAPI service (server-rendered Jinja2 + vanilla JS) backed by an embedded SQLite file (`nutrition_tracker.db`, auto-created on startup). There is one process to run; there is no separate DB server, frontend build step, or lint config.

Environment specifics for this VM:
- Python dependencies are installed into a virtualenv at `./venv` (created by the startup update script). Activate with `source venv/bin/activate`, or call binaries directly via `./venv/bin/<tool>`.
- The repo's `start.ps1` is Windows/PowerShell only — do not use it here. Run uvicorn directly instead.

Run the dev server (port 8000, hot reload):
- `./venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --reload`
- Web UI: http://127.0.0.1:8000 — API docs: http://127.0.0.1:8000/docs
- On startup the app runs `init_db()` and seeds a demo user `test` / `1234` with sample meals/workouts.

Tests and lint:
- Tests: `./venv/bin/pytest` (uses in-memory SQLite via `tests/conftest.py`; Gemini and the real DB are not touched).
- No linter or build step is configured for this project.

Gemini AI is optional. Without `GEMINI_API_KEY` (copy `.env.example` to `.env` to set it), calorie estimates and daily insights fall back to local built-in tables, and the full app still works end-to-end. The register endpoint requires a `name` field in addition to `username`/`password`.
