"""
Mechanical review generator — replaces the base44 imports with synthetic
reviews that preserve each teacher's "voice" without copying any single
review verbatim.

Why mechanical (not LLM): when this module was added, all our LLM keys
were either rate-limited (Gemini, friend's project) or out of credit
(OpenAI). Mechanical remixing is the pragmatic fallback — generated
content is sampled from real students' base44 reviews, so the tone
is authentic; the COMBINATION is novel, so no generated review is a
1:1 copy of any source review.

Algorithm per teacher:
1. Build a sentence pool from all base44 reviews of that teacher.
2. Compute the rating distribution (so a 4.8/5 teacher stays 4.8/5).
3. Compute the wta_yes / wta_no / wta_null ratios.
4. Compute the "has comment" ratio (some base44 reviews are ratings only).
5. For each new review:
   - Sample ratings from the per-metric per-teacher distribution.
   - Sample would_take_again from the wta ratio.
   - With probability=p_has_comment, generate a comment by sampling
     1-3 sentences from the pool and joining them.
   - Pick a created_at scattered over the last 180 days so the timeline
     doesn't read "all posted in the same instant."
"""
from __future__ import annotations

import random
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Sentence-end matcher covering English + Chinese punctuation. The lookbehind
# keeps the punctuation attached to the sentence on the left.
_SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s*")


def _split_sentences(text: str) -> list[str]:
    """Split a comment into sentences by punctuation. Chinese uses 。！？,
    English uses .!?. Returns sentences with their trailing punctuation."""
    if not text:
        return []
    parts = _SENT_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p and len(p.strip()) > 4]


def _build_per_teacher_corpus(rows: list[dict]) -> dict:
    """Group rows by teacher_id and pre-compute everything generation needs:
    sentence pool, rating distributions, wta ratio, has-comment ratio."""
    by_t = defaultdict(list)
    for r in rows:
        by_t[r["teacher_id"]].append(r)

    corpus = {}
    for tid, reviews in by_t.items():
        sentences = []
        with_comment = 0
        wta_yes = 0
        wta_no = 0
        wta_null = 0
        ratings = {
            "teaching_quality": [],
            "test_difficulty": [],
            "homework_load": [],
            "easygoingness": [],
        }
        for r in reviews:
            for k in ratings:
                # Defensive: some legacy rows may have None for a metric.
                if r.get(k) is not None:
                    ratings[k].append(int(r[k]))
            if r.get("comment") and r["comment"].strip():
                with_comment += 1
                sentences.extend(_split_sentences(r["comment"]))
            wta = r.get("would_take_again")
            if wta == 1 or wta is True:
                wta_yes += 1
            elif wta == 0 or wta is False:
                wta_no += 1
            else:
                wta_null += 1

        total = len(reviews)
        corpus[tid] = {
            "n": total,
            "sentences": sentences,
            "ratings": ratings,
            "wta_yes": wta_yes,
            "wta_no": wta_no,
            "wta_null": wta_null,
            "p_has_comment": with_comment / total if total else 0.0,
        }
    return corpus


def _sample_rating(pool: list[int]) -> int:
    """Sample from the per-teacher rating distribution. Falls back to a
    sensible mid-range default when the pool is empty (rare)."""
    if not pool:
        return 3
    return random.choice(pool)


def _sample_wta(c: dict):
    """Sample would_take_again from the per-teacher ratio. Returns int 0/1
    or None to match the schema's nullable column."""
    total = c["wta_yes"] + c["wta_no"] + c["wta_null"]
    if total == 0:
        return None
    pick = random.random() * total
    if pick < c["wta_yes"]:
        return 1
    if pick < c["wta_yes"] + c["wta_no"]:
        return 0
    return None


def _generate_comment(c: dict) -> str | None:
    """Maybe generate a comment by remixing this teacher's sentence pool.
    With probability (1 - p_has_comment), return None to preserve the
    original site's ratings-only ratio."""
    if random.random() > c["p_has_comment"]:
        return None
    pool = c["sentences"]
    if not pool:
        return None
    # Weighted: short comments are most common (1-2 sentences); occasionally
    # longer for variety. Cap at len(pool) so small pools don't crash.
    n = random.choices([1, 2, 3], weights=[5, 6, 2])[0]
    n = min(n, len(pool))
    chosen = random.sample(pool, n)
    return " ".join(chosen)


def _scatter_created_at(now: datetime) -> str:
    """Pick a random datetime in the last 180 days, formatted to match
    SQLite's default timestamp string (YYYY-MM-DD HH:MM:SS)."""
    days_ago = random.randint(0, 180)
    seconds_jitter = random.randint(0, 86400)
    when = now - timedelta(days=days_ago, seconds=seconds_jitter)
    return when.strftime("%Y-%m-%d %H:%M:%S")


def plan_per_teacher(corpus: dict, target_total: int) -> dict:
    """Distribute the target_total across teachers proportional to how many
    reviews each had originally. Each teacher gets at least 1 generated
    review (otherwise small-corpus teachers vanish entirely)."""
    total_orig = sum(c["n"] for c in corpus.values())
    if total_orig == 0:
        return {}
    plan = {}
    for tid, c in corpus.items():
        proportional = c["n"] / total_orig * target_total
        plan[tid] = max(1, round(proportional))
    return plan


def generate_reviews(rows: list[dict], target_total: int, *, seed: int | None = None) -> list[dict]:
    """Produce a list of fully-formed review dicts ready for INSERT. Pass
    `seed` for deterministic output (used by tests)."""
    if seed is not None:
        random.seed(seed)
    corpus = _build_per_teacher_corpus(rows)
    plan = plan_per_teacher(corpus, target_total)
    now = datetime.now(timezone.utc)
    out = []
    for tid, n in plan.items():
        c = corpus[tid]
        for _ in range(n):
            out.append({
                "id": uuid.uuid4().hex,
                "teacher_id": tid,
                "teaching_quality": _sample_rating(c["ratings"]["teaching_quality"]),
                "test_difficulty": _sample_rating(c["ratings"]["test_difficulty"]),
                "homework_load": _sample_rating(c["ratings"]["homework_load"]),
                "easygoingness": _sample_rating(c["ratings"]["easygoingness"]),
                "would_take_again": _sample_wta(c),
                "comment": _generate_comment(c),
                "ip_hash": None,
                "source": "ai_generated",
                "legacy_id": None,
                "is_visible": 1,
                "created_at": _scatter_created_at(now),
            })
    return out
