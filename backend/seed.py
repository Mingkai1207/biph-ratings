"""Seed BIPH teachers + reviews from the public base44 API.

Idempotent: re-runs are safe (upsert by legacy_id).

Usage:
    python -m backend.seed
"""
import json
import uuid
import urllib.request
from pathlib import Path

from .db import get_conn, init_db

APP_ID = "69e9d807f71b1fb4de409889"
TEACHER_URL = f"https://app.base44.com/api/apps/{APP_ID}/entities/Teacher"
REVIEW_URL = f"https://app.base44.com/api/apps/{APP_ID}/entities/Review"

# Known-noise rows the reference site accumulated
NOISE_NAMES = {"留言板", "大厨🧑\u200d🍳"}


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def is_real_teacher(t: dict) -> bool:
    name = (t.get("name") or "").strip()
    subject = (t.get("subject") or "").strip()
    if not name or not subject:
        return False
    if name in NOISE_NAMES:
        return False
    # notes/warnings use a long sentence in `subject`
    if len(subject) > 25:
        return False
    return True


def clamp_rating(v) -> int:
    if v is None:
        return 3
    try:
        r = round(float(v))
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, r))


def sync_from_base44() -> dict:
    """Pull teachers + reviews from base44 and upsert into the configured DB.
    Idempotent — only legacy_ids we haven't seen before get inserted, so it's
    safe to call repeatedly to pick up new reviews on the reference site.
    Returns a dict of before/after counts for callers (CLI + admin endpoint)."""
    init_db()

    with get_conn() as conn:
        teachers_before = conn.execute(
            "SELECT COUNT(*) AS n FROM teachers WHERE legacy_id IS NOT NULL"
        ).fetchone()["n"]
        reviews_before = conn.execute(
            "SELECT COUNT(*) AS n FROM reviews WHERE legacy_id IS NOT NULL"
        ).fetchone()["n"]

    teachers = fetch_json(TEACHER_URL)
    legacy_to_id: dict[str, str] = {}
    teachers_skipped = 0

    with get_conn() as conn:
        for row in conn.execute(
            "SELECT id, legacy_id FROM teachers WHERE legacy_id IS NOT NULL"
        ).fetchall():
            legacy_to_id[row["legacy_id"]] = row["id"]

        for t in teachers:
            if not is_real_teacher(t):
                teachers_skipped += 1
                continue
            legacy = t["id"]
            tid = legacy_to_id.get(legacy) or str(uuid.uuid4())
            legacy_to_id[legacy] = tid
            conn.execute(
                """INSERT INTO teachers (id, name, subject, legacy_id)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(legacy_id) DO UPDATE SET
                     name = excluded.name,
                     subject = excluded.subject""",
                (tid, t["name"].strip(), t["subject"].strip(), legacy),
            )

    reviews = fetch_json(REVIEW_URL)
    reviews_orphaned = 0

    with get_conn() as conn:
        for r in reviews:
            legacy_teacher = r.get("teacher_id")
            teacher_id = legacy_to_id.get(legacy_teacher)
            if not teacher_id:
                reviews_orphaned += 1
                continue
            legacy_review = r["id"]
            rid = str(uuid.uuid4())
            comment = (r.get("comment") or "").strip() or None
            try:
                conn.execute(
                    """INSERT INTO reviews
                       (id, teacher_id, teaching_quality, test_difficulty, homework_load, easygoingness,
                        comment, created_at, source, legacy_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'imported_biph_insights', ?)
                       ON CONFLICT(legacy_id) DO NOTHING""",
                    (
                        rid, teacher_id,
                        clamp_rating(r.get("teaching_quality")),
                        clamp_rating(r.get("test_difficulty")),
                        clamp_rating(r.get("homework_load")),
                        clamp_rating(r.get("easygoingness")),
                        comment,
                        r.get("created_date") or None,
                        legacy_review,
                    ),
                )
            except Exception:
                pass

    with get_conn() as conn:
        teachers_after = conn.execute(
            "SELECT COUNT(*) AS n FROM teachers WHERE legacy_id IS NOT NULL"
        ).fetchone()["n"]
        reviews_after = conn.execute(
            "SELECT COUNT(*) AS n FROM reviews WHERE legacy_id IS NOT NULL"
        ).fetchone()["n"]

    return {
        "base44_teacher_total": len(teachers),
        "base44_review_total": len(reviews),
        "teachers_before": teachers_before,
        "teachers_after": teachers_after,
        "teachers_added": teachers_after - teachers_before,
        "teachers_skipped_noise": teachers_skipped,
        "reviews_before": reviews_before,
        "reviews_after": reviews_after,
        "reviews_added": reviews_after - reviews_before,
        "reviews_orphaned": reviews_orphaned,
    }


def seed():
    """CLI entry point — prints what sync_from_base44 returns."""
    result = sync_from_base44()
    print(f"base44 had {result['base44_teacher_total']} teacher rows, "
          f"{result['base44_review_total']} review rows.")
    print(f"teachers: {result['teachers_before']} → {result['teachers_after']} "
          f"(+{result['teachers_added']}, {result['teachers_skipped_noise']} skipped as noise)")
    print(f"reviews:  {result['reviews_before']} → {result['reviews_after']} "
          f"(+{result['reviews_added']}, {result['reviews_orphaned']} orphaned)")


if __name__ == "__main__":
    seed()
