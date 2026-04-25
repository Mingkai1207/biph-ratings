"""
AI-powered smart search. The browser sends a natural-language query
("teachers with the most homework", "best math teacher", "easiest tests"),
this module asks Groq to translate it into a structured filter, and we
execute that filter against the teacher stats view as a deterministic SQL
query.

Why parse-then-execute (vs. letting the LLM read all the data and answer):
- Cheap: each call is ~300 tokens out, cents per 1000 calls vs. dollars.
- Fast: ~300ms with Groq vs. seconds for a "read everything" approach.
- Safe: the LLM cannot hallucinate a teacher name or invent a quote — it
  only emits a filter. The DB returns the actual teachers.

Falls back to keyword search if Groq is down or returns junk, so the user
always gets *something*.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import get_conn
from .spam import SpamError

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
# Llama 3.3 70B is on Groq's free tier (1000 req/day, 30 RPM as of 2026).
# Override via env if you want to A/B another model.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TIMEOUT_SEC = 8

# Per-IP daily cap for smart search. Leaves plenty of headroom under Groq's
# 1000/day free quota even with many concurrent users on the site.
MAX_AI_SEARCHES_PER_DAY = 20

# Whitelist of sort fields the parser is allowed to return. Any other value
# coerces to None (no sort). Prevents SQL injection via an unexpected field.
VALID_SORT_FIELDS = {
    "avg_rating",
    "avg_teaching_quality",
    "avg_test_difficulty",
    "avg_homework_load",
    "avg_easygoingness",
    "wta_percent",
    "review_count",
}

# Map our friendly field names to the SQL expression in TEACHER_STATS_SELECT.
# avg_rating is computed on the fly from the four metrics so it matches what
# the API returns to the browser elsewhere.
SORT_FIELD_SQL = {
    "avg_rating":           "(COALESCE(avg_tq,0)+COALESCE(avg_td,0)+COALESCE(avg_hl,0)+COALESCE(avg_eg,0))",
    "avg_teaching_quality": "avg_tq",
    "avg_test_difficulty":  "avg_td",
    "avg_homework_load":    "avg_hl",
    "avg_easygoingness":    "avg_eg",
    "wta_percent":          "(CASE WHEN wta_count > 0 THEN 100.0 * wta_yes / wta_count ELSE NULL END)",
    "review_count":         "review_count",
}

SYSTEM_PROMPT = """\
You are a query parser for an anonymous teacher review website (BIPH high school in Beijing).
Translate the user's natural-language query (in English or Chinese) into a structured JSON filter.

Each teacher has these fields:
- name (string)
- subject (one of: Math, English, Science, Arts, PE, Chinese, Humanities, Languages, Other)
- avg_rating (1-5, overall)
- avg_teaching_quality (1-5; HIGHER = better teacher)
- avg_test_difficulty (1-5; HIGHER = harder tests)
- avg_homework_load (1-5; HIGHER = more homework)
- avg_easygoingness (1-5; HIGHER = more relaxed/chill)
- wta_percent (0-100; would-take-again rate)
- review_count (int)

Return STRICT JSON ONLY (no markdown, no commentary) matching this schema:

{
  "intent": "name" | "rank" | "filter",
  "name_query": null | string,
  "sort_by": null | one of the 7 fields above,
  "order": "asc" | "desc",
  "subject_filter": null | string,
  "min_reviews": int,
  "limit": int,
  "explanation_en": string,
  "explanation_zh": string
}

Rules:
- intent="name" only when looking for a specific person ("find Mr Smith", "show me Daniel Huang").
- intent="rank" for queries like "best math teacher", "easiest tests", "who gives most homework".
- intent="filter" for queries that narrow without ordering ("math teachers").
- subject_filter must be EXACTLY one of the listed strings or null. Don't invent subjects.
- min_reviews defaults to 5 for ranking queries (so a single review can't top the chart).
- limit must be 1-20; default 10.
- Be neutral in explanations — say "lowest-rated" not "worst", "most homework" not "tortures students".
- If the query is too vague, default to: intent="rank", sort_by="avg_rating", order="desc", min_reviews=5, limit=10.

Examples:

Query: "find Mr Smith"
{"intent":"name","name_query":"Smith","sort_by":null,"order":"desc","subject_filter":null,"min_reviews":1,"limit":20,"explanation_en":"Searching for teachers named Smith.","explanation_zh":"搜索名字含 'Smith' 的老师。"}

Query: "best math teacher"
{"intent":"rank","name_query":null,"sort_by":"avg_rating","order":"desc","subject_filter":"Math","min_reviews":5,"limit":10,"explanation_en":"Top-rated Math teachers with at least 5 reviews.","explanation_zh":"评分最高的数学老师（至少 5 条评价）。"}

Query: "teacher with the most bad comments"
{"intent":"rank","name_query":null,"sort_by":"avg_rating","order":"asc","subject_filter":null,"min_reviews":5,"limit":5,"explanation_en":"Lowest-rated teachers with at least 5 reviews.","explanation_zh":"评分最低的老师（至少 5 条评价）。"}

Query: "easiest tests"
{"intent":"rank","name_query":null,"sort_by":"avg_test_difficulty","order":"asc","subject_filter":null,"min_reviews":3,"limit":10,"explanation_en":"Teachers with the easiest tests.","explanation_zh":"考试最简单的老师。"}

Query: "作业最少的老师"
{"intent":"rank","name_query":null,"sort_by":"avg_homework_load","order":"asc","subject_filter":null,"min_reviews":3,"limit":10,"explanation_en":"Teachers with the least homework.","explanation_zh":"作业最少的老师。"}

Query: "would take again"
{"intent":"rank","name_query":null,"sort_by":"wta_percent","order":"desc","subject_filter":null,"min_reviews":3,"limit":10,"explanation_en":"Teachers students most want to take again.","explanation_zh":"学生最愿意再选的老师。"}
"""


def enforce_ai_rate_limit(ip_hash: str) -> None:
    """Cap each IP at MAX_AI_SEARCHES_PER_DAY queries / 24h. Raises SpamError(429)."""
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM ai_search_log WHERE ip_hash = ? AND created_at > ?",
            (ip_hash, day_ago),
        ).fetchone()
        if row["n"] >= MAX_AI_SEARCHES_PER_DAY:
            raise SpamError(
                "rate_limited",
                f"You've hit the {MAX_AI_SEARCHES_PER_DAY}/day smart-search limit. Try again tomorrow.",
                status=429,
            )


def log_search(ip_hash: str, query: str, parsed: dict | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO ai_search_log (id, ip_hash, query, parsed) VALUES (?, ?, ?, ?)",
            (uuid.uuid4().hex, ip_hash, query[:500], json.dumps(parsed) if parsed else None),
        )


def call_groq(query: str) -> dict:
    """Make the actual Groq call. Returns the parsed JSON dict from the
    model's response. Raises on transport / auth / parse failure — caller
    decides whether to fall back to keyword search."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")

    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        # JSON mode: the model is forced to emit valid JSON. Saves us a
        # markdown-fence stripping step + makes the failure mode "Groq
        # rejects with 400" rather than "model returned prose".
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 400,
    }).encode()

    req = urllib.request.Request(
        GROQ_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=GROQ_TIMEOUT_SEC) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"]["content"]
    return json.loads(text)


def validate_parsed(p: Any) -> dict:
    """Coerce the LLM's response into a safe filter. Defaults rather than
    rejects when the model drops a field — partial parsing is still useful."""
    if not isinstance(p, dict):
        raise ValueError("parser returned non-object")

    intent = p.get("intent") if p.get("intent") in ("name", "rank", "filter") else "rank"
    sort_by = p.get("sort_by") if p.get("sort_by") in VALID_SORT_FIELDS else None
    order = p.get("order") if p.get("order") in ("asc", "desc") else "desc"
    name_query = p.get("name_query") if isinstance(p.get("name_query"), str) and p.get("name_query") else None
    subject_filter = p.get("subject_filter") if isinstance(p.get("subject_filter"), str) and p.get("subject_filter") else None
    try:
        min_reviews = int(p.get("min_reviews", 5))
    except (TypeError, ValueError):
        min_reviews = 5
    try:
        limit = int(p.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    min_reviews = max(1, min(50, min_reviews))
    limit = max(1, min(20, limit))

    return {
        "intent": intent,
        "name_query": name_query,
        "sort_by": sort_by,
        "order": order,
        "subject_filter": subject_filter,
        "min_reviews": min_reviews,
        "limit": limit,
        "explanation_en": str(p.get("explanation_en") or "Search results."),
        "explanation_zh": str(p.get("explanation_zh") or "搜索结果。"),
    }


def parse_query(query: str) -> dict:
    """End-to-end parse: call Groq, validate the response. Raises on failure."""
    raw = call_groq(query)
    return validate_parsed(raw)


def execute_search(parsed: dict) -> list[dict]:
    """Run the validated structured filter as deterministic SQL. Returns the
    same teacher dict shape as /api/teachers so the frontend renders the
    grid identically."""
    # Lazy import to avoid circular: main.py imports this module.
    from .main import TEACHER_STATS_SELECT, teacher_row_to_dict

    sql = TEACHER_STATS_SELECT
    params: list = []

    if parsed["intent"] == "name" and parsed["name_query"]:
        needle = f"%{parsed['name_query'].lower()}%"
        sql += " AND LOWER(t.name) LIKE ?"
        params.append(needle)

    if parsed["subject_filter"]:
        sql += " AND t.subject = ?"
        params.append(parsed["subject_filter"])

    sql += " GROUP BY t.id"
    sql += " HAVING review_count >= ?"
    params.append(parsed["min_reviews"])

    if parsed["sort_by"]:
        order = "DESC" if parsed["order"] == "desc" else "ASC"
        sort_expr = SORT_FIELD_SQL[parsed["sort_by"]]
        # NULLs sort last regardless of direction so meaningful values surface.
        sql += f" ORDER BY ({sort_expr}) IS NULL, ({sort_expr}) {order}"
    else:
        sql += " ORDER BY t.name"

    sql += " LIMIT ?"
    params.append(parsed["limit"])

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [teacher_row_to_dict(r) for r in rows]
