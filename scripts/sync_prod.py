#!/usr/bin/env python3
"""
Mirror production teacher + review data into the local dev DB.

One-way sync: reads from ratebiph.com's public API, wipes the local
teachers + reviews tables, re-inserts everything. Nothing we do here
touches prod — this script only writes to the local sqlite file.

Why: local dev DB drifts from production the moment real students start
submitting. Running this gives you a fresh snapshot so your localhost
looks like the real site.

Usage:
    ./venv/bin/python scripts/sync_prod.py          # asks to confirm
    ./venv/bin/python scripts/sync_prod.py --yes    # no prompt
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Make `from backend.db import ...` work when run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db  # noqa: E402

PROD = "https://ratebiph.com"
PAGE = 200  # max allowed by /api/teachers/{id}/reviews


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def fetch_all_reviews(teacher_id):
    """Paginate a teacher's reviews until has_more is false."""
    out = []
    offset = 0
    while True:
        d = fetch_json(
            f"{PROD}/api/teachers/{teacher_id}/reviews?limit={PAGE}&offset={offset}"
        )
        out.extend(d["reviews"])
        if not d.get("has_more"):
            break
        offset += PAGE
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    args = ap.parse_args()

    print(f"Target dev DB: {db.DB_PATH}")
    print(f"Source:        {PROD}")
    if not args.yes:
        ok = input("Wipe local teachers+reviews and mirror from prod? [y/N] ").lower()
        if ok != "y":
            print("Cancelled.")
            return

    db.init_db()

    print("Fetching teachers...")
    teachers = fetch_json(f"{PROD}/api/teachers")
    print(f"  {len(teachers)} teachers.")

    print("Fetching reviews...")
    all_reviews = []
    for i, t in enumerate(teachers, 1):
        rvs = fetch_all_reviews(t["id"])
        all_reviews.extend((t["id"], r) for r in rvs)
        print(f"  [{i:>2}/{len(teachers)}] {t['name']}: {len(rvs)} reviews")
    print(f"Total reviews: {len(all_reviews)}")

    # Single transaction. If anything fails mid-write, rollback leaves the
    # old dev data intact rather than a half-mirrored mess.
    with db.get_conn() as conn:
        conn.execute("DELETE FROM reviews")
        conn.execute("DELETE FROM teachers")
        for t in teachers:
            conn.execute(
                "INSERT INTO teachers (id, name, subject, courses, is_visible) "
                "VALUES (?, ?, ?, ?, 1)",
                (
                    t["id"],
                    t["name"],
                    t.get("subject"),
                    json.dumps(t.get("courses") or []),
                ),
            )
        for teacher_id, r in all_reviews:
            conn.execute(
                "INSERT INTO reviews (id, teacher_id, teaching_quality, "
                "test_difficulty, homework_load, easygoingness, would_take_again, "
                "comment, created_at, source, is_visible) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced_from_prod', 1)",
                (
                    r["id"],
                    teacher_id,
                    r["teaching_quality"],
                    r["test_difficulty"],
                    r["homework_load"],
                    r["easygoingness"],
                    r.get("would_take_again"),
                    r.get("comment"),
                    r["created_at"],
                ),
            )

    print(
        f"\nDone. {len(teachers)} teachers + {len(all_reviews)} reviews "
        f"in {db.DB_PATH}"
    )


if __name__ == "__main__":
    main()
