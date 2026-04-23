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


def seed():
    init_db()

    print(f"Fetching teachers from {TEACHER_URL}")
    teachers = fetch_json(TEACHER_URL)
    print(f"  {len(teachers)} raw entries")

    legacy_to_id: dict[str, str] = {}
    kept = 0
    skipped = 0

    with get_conn() as conn:
        # Pre-load existing legacy mappings so we keep stable UUIDs
        for row in conn.execute("SELECT id, legacy_id FROM teachers WHERE legacy_id IS NOT NULL").fetchall():
            legacy_to_id[row["legacy_id"]] = row["id"]

        for t in teachers:
            if not is_real_teacher(t):
                skipped += 1
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
            kept += 1

    print(f"  teachers: {kept} kept, {skipped} skipped (noise/incomplete)")

    print(f"Fetching reviews from {REVIEW_URL}")
    reviews = fetch_json(REVIEW_URL)
    print(f"  {len(reviews)} raw reviews")

    imported = 0
    orphaned = 0

    with get_conn() as conn:
        for r in reviews:
            legacy_teacher = r.get("teacher_id")
            teacher_id = legacy_to_id.get(legacy_teacher)
            if not teacher_id:
                orphaned += 1
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
                imported += 1
            except Exception as e:
                print(f"  skip review {legacy_review}: {e}")

    print(f"  reviews: {imported} imported, {orphaned} skipped (no matching teacher)")

    with get_conn() as conn:
        tc = conn.execute("SELECT COUNT(*) AS n FROM teachers").fetchone()["n"]
        rc = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
    print(f"DB now has {tc} teachers, {rc} reviews.")


if __name__ == "__main__":
    seed()
