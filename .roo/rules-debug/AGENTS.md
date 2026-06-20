# AGENTS.md - Debug Mode Rules

This file provides debugging guidance specific to this repository.

## Critical Debug Rules (Non-Obvious)

- **Tests use in-memory SQLite** - the database is recreated per test via conftest fixtures. No persistent state between tests.
- **HTTP client fixtures monkeypatch multiple settings** - `SETUP_COMPLETE`, `SUWAYOMI_*`, `LIBRARY_PATH` are overridden. Real values only in integration tests.
- **Scheduler is disabled in unit test fixtures** - `scheduler.start/shutdown/add_job` are lambda no-ops. Real APScheduler only in integration tests.
- **Integration tests require running Suwayomi instance** - marked `@pytest.mark.integration`, skip if `.env.test` missing `SUWAYOMI_URL`.
- **Logging configured via dictConfig in `app/main.py`** - `otaki.*` loggers at INFO, `sqlalchemy.engine` at WARNING, `gql`/`httpx` silenced.
- **Environment file path controlled by `ENV_FILE` env var** - defaults to `.env` relative to backend directory.
