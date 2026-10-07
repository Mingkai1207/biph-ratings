"""Base44 merges preserve submissions, moderation, and review identities."""
import sqlite3

import pytest

from backend import db, seed


@pytest.fixture
def source(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "merge.db"))
    db.init_db()
    data = {
        seed.TEACHER_URL: [
            {"id": "teacher-source", "name": "Long Subject Teacher",
             "subject": "Environmental Science/Biology"},
        ],
        seed.REVIEW_URL: [
            {"id": "review-source", "teacher_id": "teacher-source",
             "teaching_quality": 5, "test_difficulty": 2,
             "homework_load": 3, "easygoingness": 4,
             "comment": "Original student comment",
             "created_date": "2026-10-02T03:47:59Z"},
        ],
    }
    monkeypatch.setattr(seed, "fetch_json", lambda url: data[url])
    return data


def test_merge_long_subject_reviews_once_and_preserve_native_submissions(source):
    with db.get_conn() as conn:
        conn.execute("INSERT INTO teachers (id, name, subject) VALUES ('native', 'Native', 'Math')")
        conn.execute(
            """INSERT INTO reviews
               (id, teacher_id, teaching_quality, test_difficulty, homework_load,
                easygoingness, comment, is_visible)
               VALUES ('native-review', 'native', 4, 3, 2, 5, 'Keep me', 0)"""
        )
    first = seed.sync_from_base44()
    second = seed.sync_from_base44()
    assert first["teachers_added"] == first["reviews_added"] == 1
    assert second["teachers_added"] == second["reviews_added"] == 0
    with db.get_conn() as conn:
        native = conn.execute("SELECT * FROM reviews WHERE id = 'native-review'").fetchone()
        imported = conn.execute("SELECT * FROM reviews WHERE legacy_id = 'review-source'").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 2
        assert native["comment"] == "Keep me" and native["is_visible"] == 0
        assert imported["comment"] == "Original student comment"
        assert imported["created_at"] == "2026-10-02T03:47:59Z"
        assert imported["teaching_quality"] == 5 and imported["test_difficulty"] == 2
        assert imported["source"] == "imported_biph_insights"


@pytest.mark.parametrize("fields,visible", [
    ({}, 1),
    ({"moderation_status": "approved", "is_retracted": False}, 1),
    ({"moderation_status": "rejected"}, 0),
    ({"moderation_status": "pending"}, 0),
    ({"is_retracted": True}, 0),
])
def test_source_moderation_is_preserved(source, fields, visible):
    source[seed.REVIEW_URL][0].update(fields)
    seed.sync_from_base44()
    with db.get_conn() as conn:
        row = conn.execute("SELECT is_visible FROM reviews").fetchone()
        assert row[0] == visible


def test_later_source_withdrawal_hides_review_without_replacing_id(source):
    seed.sync_from_base44()
    with db.get_conn() as conn:
        original_id = conn.execute("SELECT id FROM reviews").fetchone()[0]
    source[seed.REVIEW_URL][0]["is_retracted"] = True
    seed.sync_from_base44()
    with db.get_conn() as conn:
        row = conn.execute("SELECT id, is_visible FROM reviews").fetchone()
        assert row["id"] == original_id and row["is_visible"] == 0


def test_sync_never_unhides_locally_moderated_review(source):
    seed.sync_from_base44()
    with db.get_conn() as conn:
        conn.execute("UPDATE reviews SET is_visible = 0")
    seed.sync_from_base44()
    with db.get_conn() as conn:
        assert conn.execute("SELECT is_visible FROM reviews").fetchone()[0] == 0


def test_nonteacher_and_orphan_reviews_are_excluded_even_with_old_mapping(source):
    source[seed.TEACHER_URL].append(
        {"id": "noise", "name": "留言板", "subject": "Comments"}
    )
    with db.get_conn() as conn:
        conn.execute("INSERT INTO teachers (id, name, legacy_id) VALUES ('old-noise', '留言板', 'noise')")
    for teacher_id in ("noise", "missing"):
        source[seed.REVIEW_URL].append({
            **source[seed.REVIEW_URL][0], "id": teacher_id, "teacher_id": teacher_id,
        })
    result = seed.sync_from_base44()
    assert result["teachers_skipped_noise"] == 1
    assert result["reviews_orphaned"] == 2
    assert result["reviews_added"] == 1


def test_invalid_review_rolls_back_entire_merge_instead_of_silent_loss(source):
    source[seed.REVIEW_URL].append({
        **source[seed.REVIEW_URL][0], "id": "invalid", "created_date": None,
    })
    with pytest.raises(sqlite3.IntegrityError):
        seed.sync_from_base44()
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0


def test_failed_source_fetch_does_not_change_teacher_roster(source, monkeypatch):
    def failed_fetch(url):
        if url == seed.REVIEW_URL:
            raise OSError("source unavailable")
        return source[url]
    monkeypatch.setattr(seed, "fetch_json", failed_fetch)
    with pytest.raises(OSError, match="source unavailable"):
        seed.sync_from_base44()
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] == 0
