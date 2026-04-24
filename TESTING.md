# Testing

100% test coverage is the key to great vibe coding. Tests let you move fast,
trust your instincts, and ship with confidence. Without them, vibe coding is
just yolo coding. With them, it's a superpower.

## Stack

- **pytest 8.3** — test runner
- **pytest-cov 5.0** — coverage reporting
- **httpx 0.27** — the transport behind FastAPI's `TestClient`

Config lives in `pytest.ini`. Tests live in `tests/`.

## Run

From the repo root:

```bash
./venv/bin/python -m pytest              # full suite
./venv/bin/python -m pytest -x           # stop on first failure
./venv/bin/python -m pytest -k cards     # filter by name
./venv/bin/python -m pytest --cov=backend  # with coverage
```

## Test Isolation

`tests/conftest.py` creates a fresh SQLite file under `/tmp/biph-test-<uuid>.db`
per pytest session by setting `BIPH_DB_PATH` before `backend.db` is imported.
It also sets `TURNSTILE_ENABLED=0` so Cloudflare verification is bypassed.

The `_init_test_db` session fixture runs `db.init_db()` once, then deletes the
temp file on teardown. Tests never touch `backend/biph.db`.

## Layers

| Layer | What | Where |
|---|---|---|
| Unit | Pure functions (`spam.check_comment`, `cards._fit_text`) | `tests/test_*.py` |
| Integration | HTTP endpoints via `TestClient` | `tests/test_api.py` |
| Smoke / E2E | Browser-based QA via `/qa` skill | `.gstack/qa-reports/` |

## Conventions

- **Name tests by behavior, not by function**: `test_teacher_detail_computes_averages`, not `test_get_teacher`.
- **Assert on values, not shapes alone**: `assert data["review_count"] == 3`, not `assert "review_count" in data`.
- **One concept per test**: if you're writing "and" in the docstring, split it.
- **Use fixtures for seed data**: don't POST through the API just to set up state — insert directly via `db.get_conn()` so tests stay focused.
- **Never check in real credentials**: tests run with `TURNSTILE_ENABLED=0` and a test-only admin token.

## When to Write a Test

- New endpoint → integration test for the happy path + one error path.
- Bug fix → regression test that would have caught the bug.
- New conditional (`if`/`else`, error branch) → test both paths.
- Never commit code that makes existing tests fail.
