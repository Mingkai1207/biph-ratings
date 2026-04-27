"""
Test setup. Two things have to happen BEFORE backend.db is imported:

1. Point BIPH_DB_PATH at a temp sqlite file so tests don't touch biph.db.
2. Disable Turnstile verification (TURNSTILE_SECRET unset -> verify_turnstile
   short-circuits in tests).

Because backend.db captures DB_PATH at module import time, we set the env
var at the top of this file, which pytest loads before collecting tests.
"""
import os
import tempfile
import uuid
from pathlib import Path

# Must run before any `from backend...` import.
_TMP_DB = Path(tempfile.gettempdir()) / f"biph-test-{uuid.uuid4().hex}.db"
os.environ["BIPH_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ["TURNSTILE_ENABLED"] = "0"  # skip Cloudflare verification in tests
# Disable the background base44 sync loop in tests so we don't make outbound
# HTTP calls during the suite (the loop only starts when interval > 0).
os.environ["BASE44_SYNC_INTERVAL_SEC"] = "0"

import pytest
from fastapi.testclient import TestClient

from backend import db as _db  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Create schema once per test session, delete the file afterward."""
    _db.init_db()
    yield
    try:
        _TMP_DB.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture
def client():
    """Fresh TestClient. Tests should not rely on cross-test state — use
    helper fixtures below to seed what they need."""
    return TestClient(app)


@pytest.fixture
def seeded_teacher(client):
    """Insert one visible teacher directly and return its id. Bypasses the
    submission/approval flow so tests stay focused."""
    teacher_id = uuid.uuid4().hex
    with _db.get_conn() as conn:
        conn.execute(
            "INSERT INTO teachers (id, name, subject, is_visible) "
            "VALUES (?, ?, ?, 1)",
            (teacher_id, "Test Teacher", "Math"),
        )
    return teacher_id


@pytest.fixture
def seeded_teacher_with_reviews(client):
    """Teacher + 3 reviews so stats/averages have something to compute."""
    teacher_id = uuid.uuid4().hex
    with _db.get_conn() as conn:
        conn.execute(
            "INSERT INTO teachers (id, name, subject, is_visible) "
            "VALUES (?, ?, ?, 1)",
            (teacher_id, "Reviewed Teacher", "Physics"),
        )
        for tq, td, hl, eg in [(5, 3, 2, 4), (4, 3, 3, 4), (5, 2, 2, 5)]:
            conn.execute(
                "INSERT INTO reviews (id, teacher_id, teaching_quality, "
                "test_difficulty, homework_load, easygoingness, comment, "
                "is_visible) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (uuid.uuid4().hex, teacher_id, tq, td, hl, eg, "ok"),
            )
    return teacher_id
