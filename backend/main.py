import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, conint

from .cards import render_teacher_card, render_teacher_qr
from .db import get_conn, init_db
from .spam import (
    TEACHER_COOLDOWN_DAYS,
    SpamError,
    check_comment,
    check_suggestion,
    enforce_rate_limit,
    enforce_suggestion_rate_limit,
    hash_ip,
    verify_turnstile,
)

def _parse_admin_tokens() -> set:
    """Build the set of accepted admin tokens from env. Two sources, both
    optional, unioned together so the existing single ADMIN_TOKEN keeps
    working alongside the multi-token ADMIN_TOKENS list:

      ADMIN_TOKEN   = "primary-token"                  (single, legacy)
      ADMIN_TOKENS  = "tok-1,tok-2,tok-3"              (multi, comma-sep)

    If neither is set we fall back to a dev-only default so local runs
    don't 401 every admin request."""
    tokens = set()
    single = os.environ.get("ADMIN_TOKEN", "").strip()
    if single:
        tokens.add(single)
    multi = os.environ.get("ADMIN_TOKENS", "").strip()
    if multi:
        for piece in multi.split(","):
            t = piece.strip()
            if t:
                tokens.add(t)
    if not tokens:
        tokens.add("dev-admin-token")
    return tokens


ADMIN_TOKENS = _parse_admin_tokens()
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Auto-sync interval. Default 24h; set BASE44_SYNC_INTERVAL_SEC=0 to disable
# (useful for tests + local dev where you don't want background HTTP traffic).
BASE44_SYNC_INTERVAL_SEC = int(os.environ.get("BASE44_SYNC_INTERVAL_SEC", "86400"))
# Wait this long after boot before the first sync, so a redeploy doesn't
# immediately hammer base44 every time we push code.
BASE44_SYNC_INITIAL_DELAY_SEC = int(os.environ.get("BASE44_SYNC_INITIAL_DELAY_SEC", "300"))

# How long after submission the author can take their review back. Short on
# purpose: this is a "oops, I misclicked a star" undo, not an edit-as-you-please
# affordance. After the window expires the review locks in like normal.
REVOKE_WINDOW_SECONDS = 60

# Maintenance mode: when MAINTENANCE_MODE=1 in env, every public route serves
# a maintenance page instead of the real content. Admin routes still work
# (so I can still run regenerate / stats / etc.) so we can iterate while the
# site is dark to students. Toggle on Railway: `railway variables --set
# MAINTENANCE_MODE=1` to take it down, `--set MAINTENANCE_MODE=0` to bring
# it back.
MAINTENANCE_MODE = os.environ.get("MAINTENANCE_MODE", "0") == "1"

# Single-origin hosting means CORS rarely matters, but set a sensible default list:
# the prod domain + its www alias. Override with ALLOWED_ORIGIN env for custom setups.
DEFAULT_ALLOWED = ["https://ratebiph.com", "https://www.ratebiph.com"]

app = FastAPI(title="BIPH Rate My Teacher API")

if ALLOWED_ORIGIN == "*":
    cors_origins = ["*"]
elif "," in ALLOWED_ORIGIN:
    cors_origins = [o.strip() for o in ALLOWED_ORIGIN.split(",") if o.strip()]
else:
    cors_origins = [ALLOWED_ORIGIN] if ALLOWED_ORIGIN else DEFAULT_ALLOWED

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


_MAINTENANCE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Rate BIPH — 暂停服务 / Paused</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: ui-serif, Georgia, "Songti SC", serif;
      background: oklch(0.96 0.02 75);
      color: oklch(0.25 0.02 60);
    }
    .box {
      max-width: 520px;
      padding: 48px 32px;
      text-align: center;
    }
    h1 {
      font-size: 38px;
      font-weight: 400;
      letter-spacing: -0.02em;
      margin: 0 0 22px;
    }
    h1 em { color: oklch(0.55 0.12 40); font-style: italic; }
    p {
      font-size: 16px;
      line-height: 1.7;
      color: oklch(0.42 0.02 60);
      margin: 0 0 14px;
    }
    .en {
      margin-top: 22px;
      padding-top: 22px;
      border-top: 1px solid oklch(0.85 0.02 60);
    }
    .small {
      margin-top: 26px;
      font-size: 13px;
      color: oklch(0.55 0.02 60);
      font-style: italic;
    }
  </style>
</head>
<body>
  <div class="box">
    <h1>Rate BIPH <em>暂停服务</em></h1>
    <p>正在跟 <strong>BIPH Insights</strong> 原作者商讨网站合并的事。</p>
    <p>具体怎么做，等 <strong>AP 考试结束</strong> 之后再商量。</p>
    <div class="en">
      <p>Currently in talks with the original BIPH Insights team about merging the two sites.</p>
      <p>Details get figured out <strong>after AP exams</strong>.</p>
    </div>
    <p class="small">回头见。See you after AP.</p>
  </div>
</body>
</html>
"""


PREVIEW_COOKIE = "rb_preview"


@app.middleware("http")
async def _maintenance_gate(request, call_next):
    """When MAINTENANCE_MODE is on, every non-admin route serves a 503
    maintenance page. Admin routes still pass through so we can keep using
    /api/admin/* (stats, regenerate-reviews, etc.) while the site is dark
    to students. Health check also passes so Railway doesn't restart us.

    Preview bypass: pass `?preview=<admin_token>` once. We set a session
    cookie carrying the same token, and from then on every request from
    that browser (including the JS XHRs that hit /api/teachers etc.)
    sees the cookie and bypasses the gate. Lets an admin QA the live
    site through the maintenance wall without flipping the flag off for
    everyone."""
    if not MAINTENANCE_MODE:
        return await call_next(request)
    path = request.url.path
    if path.startswith("/api/admin/") or path == "/api/health":
        return await call_next(request)
    preview_token = request.query_params.get("preview", "")
    cookie_token = request.cookies.get(PREVIEW_COOKIE, "")
    # Explicit logout: ?preview=logout clears the cookie + serves the
    # maintenance page like normal. Lets an admin verify what students
    # are seeing without manually digging into devtools.
    if preview_token == "logout":
        response = Response(
            content=_MAINTENANCE_HTML,
            status_code=503,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )
        response.delete_cookie(PREVIEW_COOKIE)
        return response
    valid_query = preview_token and preview_token in ADMIN_TOKENS
    valid_cookie = cookie_token and cookie_token in ADMIN_TOKENS
    if valid_query or valid_cookie:
        response = await call_next(request)
        if valid_query:
            # Promote the query-param token to a cookie so subsequent XHR
            # calls (which won't carry the query param) keep bypassing.
            response.set_cookie(
                PREVIEW_COOKIE, preview_token,
                httponly=True, samesite="lax", max_age=86400,
                secure=request.url.scheme == "https",
            )
        return response
    return Response(
        content=_MAINTENANCE_HTML,
        status_code=503,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.on_event("startup")
def _startup():
    init_db()


@app.on_event("startup")
async def _start_base44_sync_loop():
    """Kick off the background base44 sync loop. Skipped when interval=0
    (tests + local dev) so pytest doesn't make outbound HTTP calls."""
    if BASE44_SYNC_INTERVAL_SEC > 0:
        asyncio.create_task(_base44_sync_loop())


async def _base44_sync_loop():
    """Daily idempotent pull from base44. sync_from_base44 is synchronous
    (urllib + sqlite), so we run it in the default executor to keep the
    event loop responsive while a sync is in flight (~10-30s per pull).

    Failures are caught and logged so a transient base44 outage or DB
    hiccup doesn't kill the loop — we just try again next interval."""
    from .seed import sync_from_base44

    await asyncio.sleep(BASE44_SYNC_INITIAL_DELAY_SEC)
    while True:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, sync_from_base44)
            print(
                f"[base44 auto-sync] +{result['reviews_added']} reviews, "
                f"+{result['teachers_added']} teachers "
                f"(now {result['reviews_after']} / {result['teachers_after']})"
            )
        except Exception as e:
            # Single-line log so it's grep-able in Railway's log viewer.
            print(f"[base44 auto-sync] FAILED: {type(e).__name__}: {e}")
        await asyncio.sleep(BASE44_SYNC_INTERVAL_SEC)


@app.exception_handler(SpamError)
async def spam_error_handler(request: Request, exc: SpamError):
    return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})


Rating = conint(ge=1, le=5)


class ReviewIn(BaseModel):
    teaching_quality: Rating
    test_difficulty: Rating
    homework_load: Rating
    easygoingness: Rating
    # Optional yes/no: null = reviewer skipped the question, so it won't count
    # toward the teacher's % (matches RMP behavior where this is a separate stat).
    would_take_again: Optional[bool] = None
    comment: Optional[str] = None
    turnstile_token: Optional[str] = None


class CoursesIn(BaseModel):
    courses: str = Field(min_length=1, max_length=300)


class TeacherSubmitIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    subject: Optional[str] = Field(default=None, max_length=60)
    # Comma-separated course list — e.g. "AP Calculus BC, Precalculus". We
    # normalize it on the server (strip, dedupe, rejoin with ", ").
    courses: Optional[str] = Field(default=None, max_length=300)
    turnstile_token: Optional[str] = None


class SuggestionIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    turnstile_token: Optional[str] = None


class VoteIn(BaseModel):
    # 1 = thumbs up, -1 = thumbs down, 0 = clear my vote.
    # The client sends the *desired final state*, not a delta, so flipping
    # sides is one request instead of two (delete + insert).
    vote: conint(ge=-1, le=1)


class TeacherEditIn(BaseModel):
    """Admin-only edit. Both fields optional — only what's provided gets
    updated. Length bounds match the submission validator so admin edits
    can't write values that POST /api/teachers/submit would reject."""
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    subject: Optional[str] = Field(default=None, max_length=60)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def parse_courses(raw):
    """Normalize a comma-separated courses string into a clean list."""
    if not raw:
        return []
    seen = []
    for piece in raw.split(","):
        c = piece.strip()
        if c and c not in seen:
            seen.append(c)
    return seen


def normalize_courses_input(raw: Optional[str]) -> Optional[str]:
    cleaned = parse_courses(raw)
    return ", ".join(cleaned) if cleaned else None


def teacher_row_to_dict(row):
    metric_avgs = [row["avg_tq"], row["avg_td"], row["avg_hl"], row["avg_eg"]]
    present = [v for v in metric_avgs if v is not None]
    overall = round(sum(present) / len(present), 2) if present else None
    # "Would take again": only computed from reviews where the reviewer
    # actually answered. wta_count = how many yes-or-no answers we have.
    wta_count = row["wta_count"] if "wta_count" in row.keys() else 0
    wta_yes = row["wta_yes"] if "wta_yes" in row.keys() else 0
    wta_percent = round(100.0 * wta_yes / wta_count) if wta_count else None
    return {
        "id": row["id"],
        "name": row["name"],
        "subject": row["subject"],
        "courses": parse_courses(row["courses"] if "courses" in row.keys() else None),
        "avg_rating": overall,
        "avg_teaching_quality": round(row["avg_tq"], 2) if row["avg_tq"] is not None else None,
        "avg_test_difficulty": round(row["avg_td"], 2) if row["avg_td"] is not None else None,
        "avg_homework_load": round(row["avg_hl"], 2) if row["avg_hl"] is not None else None,
        "avg_easygoingness": round(row["avg_eg"], 2) if row["avg_eg"] is not None else None,
        "review_count": row["review_count"],
        "wta_percent": wta_percent,
        "wta_count": wta_count,
    }


TEACHER_STATS_SELECT = """
    SELECT
      t.id, t.name, t.subject, t.courses,
      AVG(CASE WHEN r.is_visible = 1 THEN r.teaching_quality END) AS avg_tq,
      AVG(CASE WHEN r.is_visible = 1 THEN r.test_difficulty  END) AS avg_td,
      AVG(CASE WHEN r.is_visible = 1 THEN r.homework_load    END) AS avg_hl,
      AVG(CASE WHEN r.is_visible = 1 THEN r.easygoingness    END) AS avg_eg,
      COALESCE(SUM(CASE WHEN r.is_visible = 1 THEN 1 ELSE 0 END), 0) AS review_count,
      COALESCE(SUM(CASE WHEN r.is_visible = 1 AND r.would_take_again IS NOT NULL THEN 1 ELSE 0 END), 0) AS wta_count,
      COALESCE(SUM(CASE WHEN r.is_visible = 1 AND r.would_take_again = 1 THEN 1 ELSE 0 END), 0) AS wta_yes
    FROM teachers t
    LEFT JOIN reviews r ON r.teacher_id = t.id
    WHERE t.is_visible = 1
"""


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/subjects")
def list_subjects():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT subject FROM teachers WHERE is_visible = 1 AND subject IS NOT NULL ORDER BY subject"
        ).fetchall()
    return [r["subject"] for r in rows]


@app.get("/api/teachers")
def list_teachers(
    q: Optional[str] = Query(default=None),
    subject: Optional[str] = Query(default=None),
):
    sql = TEACHER_STATS_SELECT
    params: list = []
    if q:
        needle = f"%{q.lower()}%"
        sql += " AND (LOWER(t.name) LIKE ? OR LOWER(COALESCE(t.courses, '')) LIKE ?)"
        params.extend([needle, needle])
    if subject and subject != "All":
        sql += " AND t.subject = ?"
        params.append(subject)
    sql += " GROUP BY t.id ORDER BY t.name"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [teacher_row_to_dict(r) for r in rows]


class AISearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=200)


@app.post("/api/search")
def ai_search(payload: AISearchIn, request: Request):
    """Smart search: parse natural language → structured filter → SQL.
    Falls back to keyword search if Groq is unreachable so the user always
    gets *something* back rather than a 500."""
    from . import aisearch

    iph = hash_ip(client_ip(request))
    aisearch.enforce_ai_rate_limit(iph)

    try:
        parsed = aisearch.parse_query(payload.query)
        teachers = aisearch.execute_search(parsed)
        aisearch.log_search(iph, payload.query, parsed)
        return {
            "teachers": teachers,
            "explanation_en": parsed["explanation_en"],
            "explanation_zh": parsed["explanation_zh"],
            "parsed": parsed,
            "fallback": False,
        }
    except SpamError:
        raise
    except Exception as e:
        # LLM down / quota / parse failure — degrade to keyword search so
        # the UI doesn't dead-end. Log loudly so we can fix the underlying
        # provider issue (this used to swallow silently and hide config bugs).
        import logging
        logging.exception(
            "[smart-search] %s fallback (provider=%s) on query=%r: %s",
            type(e).__name__, aisearch.active_provider(), payload.query[:80], e,
        )
        aisearch.log_search(iph, payload.query, None)
        teachers = list_teachers(q=payload.query, subject=None)
        # Distinguish "we deliberately throttled" from "upstream broke" so
        # the UI can show a calmer message — the former is just "try again
        # in a sec," not "smart search is down."
        if isinstance(e, aisearch.LLMRateLimited):
            en_msg = "Smart search is busy right now — keyword results below. Try again in a minute."
            zh_msg = "智能搜索现在忙不过来，先给你关键词匹配结果。一分钟后再试一下。"
        else:
            en_msg = "Smart search unavailable; showing keyword matches."
            zh_msg = "智能搜索暂不可用；以下是关键词匹配结果。"
        return {
            "teachers": teachers,
            "explanation_en": en_msg,
            "explanation_zh": zh_msg,
            "parsed": None,
            "fallback": True,
        }


@app.get("/api/teachers/{teacher_id}")
def get_teacher(teacher_id: str, request: Request):
    sql = TEACHER_STATS_SELECT + " AND t.id = ? GROUP BY t.id"
    iph = hash_ip(client_ip(request))
    cooldown_start = (datetime.now(timezone.utc) - timedelta(days=TEACHER_COOLDOWN_DAYS)).isoformat()
    with get_conn() as conn:
        row = conn.execute(sql, (teacher_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Teacher not found")
        # Rating distribution on teaching_quality, same connection
        dist_rows = conn.execute(
            """SELECT teaching_quality AS r, COUNT(*) AS n FROM reviews
               WHERE teacher_id = ? AND is_visible = 1 GROUP BY teaching_quality""",
            (teacher_id,),
        ).fetchall()
        # "Has the requester already reviewed this teacher in the last N days?"
        # We DON'T filter on is_visible here — rate limiting doesn't either, so the
        # two must agree. If admin hid the review the user still can't re-post, and
        # it's fine to show the rating back to them (they wrote it).
        my_review_row = conn.execute(
            """SELECT id, teaching_quality, test_difficulty, homework_load, easygoingness,
                      would_take_again, comment, created_at
               FROM reviews
               WHERE teacher_id = ? AND ip_hash = ? AND created_at > ?
               ORDER BY created_at DESC
               LIMIT 1""",
            (teacher_id, iph, cooldown_start),
        ).fetchone()
    d = teacher_row_to_dict(row)
    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in dist_rows:
        dist[r["r"]] = r["n"]
    d["distribution"] = dist
    if my_review_row:
        mr = dict(my_review_row)
        mr["cooldown_days"] = TEACHER_COOLDOWN_DAYS
        # Tell the frontend the revoke window so the countdown UI is one
        # source of truth (server). UI shows the button only inside this window.
        mr["revoke_window_seconds"] = REVOKE_WINDOW_SECONDS
        d["my_recent_review"] = mr
    else:
        d["my_recent_review"] = None
    return d


def _site_base(request: Request) -> tuple[str, str]:
    """Resolve (full URL prefix, short display label) for share assets.

    Preference order:
      1. SITE_URL env var (explicit override for prod).
      2. x-forwarded-proto + host headers (Railway proxies + custom domains).
      3. Fall back to request.url.scheme + request headers host.

    The display label strips the protocol so it reads cleanly on the card.
    """
    base = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if not base:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", "ratebiph.com")
        base = f"{scheme}://{host}"
    label = base.replace("https://", "").replace("http://", "").rstrip("/")
    return base, label


def _fetch_teacher_stats(teacher_id: str) -> dict:
    sql = TEACHER_STATS_SELECT + " AND t.id = ? GROUP BY t.id"
    with get_conn() as conn:
        row = conn.execute(sql, (teacher_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return teacher_row_to_dict(row)


@app.get("/api/teachers/{teacher_id}/card.png")
def teacher_card_png(teacher_id: str, request: Request):
    """1080x1350 social-share card — designed for Xiaohongshu + WeChat status.

    Cache-Control: 5-minute public cache so reshares don't re-render every
    time, but new reviews land fast enough on the card for the feedback loop
    to feel alive.
    """
    d = _fetch_teacher_stats(teacher_id)
    base, label = _site_base(request)
    png = render_teacher_card(
        name=d["name"],
        subject=d["subject"],
        rating=d["avg_rating"],
        review_count=d["review_count"],
        wta_percent=d["wta_percent"],
        wta_count=d["wta_count"],
        qr_url=f"{base}/teacher.html?id={teacher_id}",
        site_label=label,
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/api/teachers/{teacher_id}/qr.png")
def teacher_qr_png(teacher_id: str, request: Request):
    """1024x1024 printable poster — print and tape outside classrooms."""
    d = _fetch_teacher_stats(teacher_id)
    base, label = _site_base(request)
    png = render_teacher_qr(
        name=d["name"],
        subject=d["subject"],
        qr_url=f"{base}/teacher.html?id={teacher_id}",
        site_label=label,
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=600"},
    )


@app.get("/api/teachers/{teacher_id}/reviews")
def list_reviews(
    teacher_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    iph = hash_ip(client_ip(request))
    with get_conn() as conn:
        # Join vote aggregates and the caller's own vote in one query. LEFT JOIN
        # on a subquery keeps reviews with zero votes visible — they just come
        # back with NULL counts that we COALESCE to 0.
        rows = conn.execute(
            """SELECT r.id, r.teaching_quality, r.test_difficulty, r.homework_load, r.easygoingness,
                      r.would_take_again, r.comment, r.created_at,
                      COALESCE(v.likes, 0) AS likes,
                      COALESCE(v.dislikes, 0) AS dislikes,
                      mv.vote AS my_vote
               FROM reviews r
               LEFT JOIN (
                 SELECT review_id,
                        SUM(CASE WHEN vote =  1 THEN 1 ELSE 0 END) AS likes,
                        SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END) AS dislikes
                 FROM review_votes GROUP BY review_id
               ) v ON v.review_id = r.id
               LEFT JOIN review_votes mv ON mv.review_id = r.id AND mv.ip_hash = ?
               WHERE r.teacher_id = ? AND r.is_visible = 1
               ORDER BY
                 -- Section 1: reviews with a real comment. Section 2: rating-only.
                 CASE WHEN r.comment IS NOT NULL AND TRIM(r.comment) != '' THEN 0 ELSE 1 END,
                 -- Within each section: most-liked first. Ignore dislikes (per user).
                 COALESCE(v.likes, 0) DESC,
                 -- Stable tiebreak: newer reviews win ties on likes.
                 r.created_at DESC
               LIMIT ? OFFSET ?""",
            (iph, teacher_id, limit, offset),
        ).fetchall()
    return {
        "reviews": [dict(r) for r in rows],
        "has_more": len(rows) == limit,
    }


@app.post("/api/reviews/{review_id}/vote")
def vote_on_review(review_id: str, body: VoteIn, request: Request):
    """Thumbs up/down on a review comment. Keyed by ip_hash so each IP gets
    one vote per review — not bulletproof against shared IPs or VPN rotation,
    but it's the same identity model the rest of the site uses."""
    iph = hash_ip(client_ip(request))
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM reviews WHERE id = ? AND is_visible = 1",
            (review_id,),
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Review not found")
        if body.vote == 0:
            conn.execute(
                "DELETE FROM review_votes WHERE review_id = ? AND ip_hash = ?",
                (review_id, iph),
            )
        else:
            # Upsert — inserts on first vote, flips sides on repeat vote.
            conn.execute(
                """INSERT INTO review_votes (review_id, ip_hash, vote) VALUES (?, ?, ?)
                   ON CONFLICT(review_id, ip_hash) DO UPDATE SET vote = excluded.vote""",
                (review_id, iph, body.vote),
            )
        counts = conn.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN vote =  1 THEN 1 ELSE 0 END), 0) AS likes,
                 COALESCE(SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END), 0) AS dislikes
               FROM review_votes WHERE review_id = ?""",
            (review_id,),
        ).fetchone()
    return {
        "ok": True,
        "likes": counts["likes"],
        "dislikes": counts["dislikes"],
        "my_vote": body.vote if body.vote != 0 else None,
    }


@app.post("/api/teachers/{teacher_id}/reviews")
def post_review(teacher_id: str, body: ReviewIn, request: Request):
    with get_conn() as conn:
        t = conn.execute("SELECT id FROM teachers WHERE id = ? AND is_visible = 1", (teacher_id,)).fetchone()
    if not t:
        raise HTTPException(status_code=404, detail="Teacher not found")

    ip = client_ip(request)
    if not verify_turnstile(body.turnstile_token, ip):
        raise SpamError("captcha_failed", "Captcha verification failed. Refresh and try again.", status=400)

    comment = check_comment(body.comment)
    iph = hash_ip(ip)
    enforce_rate_limit(iph, teacher_id, comment)

    review_id = str(uuid.uuid4())
    # None => unanswered; bool => 0/1. Keeping null in the DB so unanswered
    # doesn't count toward the % — matches the CHECK constraint on the column.
    wta = None if body.would_take_again is None else (1 if body.would_take_again else 0)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO reviews
               (id, teacher_id, teaching_quality, test_difficulty, homework_load, easygoingness,
                would_take_again, comment, ip_hash, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'user')""",
            (
                review_id, teacher_id,
                body.teaching_quality, body.test_difficulty, body.homework_load, body.easygoingness,
                wta, comment, iph,
            ),
        )
    return {"ok": True, "id": review_id}


@app.post("/api/reviews/{review_id}/revoke")
def revoke_review(review_id: str, request: Request):
    """Author can take their own review back within REVOKE_WINDOW_SECONDS.
    Verified by ip_hash match (same auth model as the cooldown check), so a
    stranger can't delete someone else's review even if they have the id.
    Hard-deletes — the user is undoing their own action, not the admin
    hiding it."""
    iph = hash_ip(client_ip(request))
    with get_conn() as conn:
        row = conn.execute(
            "SELECT ip_hash, created_at FROM reviews WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Review not found")
        if row["ip_hash"] != iph:
            # Don't reveal whether it exists vs. wrong author — same 403 either way.
            raise HTTPException(status_code=403, detail="Not your review")
        # SQLite stores timestamps as ISO strings via the schema default; parse
        # tolerantly. created_at may or may not have a trailing 'Z'.
        created_raw = row["created_at"]
        try:
            if isinstance(created_raw, str):
                # 'YYYY-MM-DD HH:MM:SS' from sqlite default; treat as UTC.
                created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            else:
                created = created_raw
        except Exception:
            raise HTTPException(status_code=500, detail="Bad created_at")
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if age > REVOKE_WINDOW_SECONDS:
            raise HTTPException(
                status_code=410,
                detail=f"Revoke window expired ({REVOKE_WINDOW_SECONDS}s)",
            )
        conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
        # Vote rows are fk-cascaded by schema; no manual cleanup needed.
    return {"ok": True}


@app.post("/api/teachers/{teacher_id}/courses")
def set_teacher_courses(teacher_id: str, body: CoursesIn, request: Request):
    """First-submitter-wins: lets anyone fill in the course list for a teacher,
    but only if it's currently empty. Once set, writes are rejected with 409
    so the field effectively locks. Admins can clear it if a bad value sticks.

    The write is atomic: we UPDATE only rows where courses IS NULL or empty,
    then check rowcount. Two concurrent POSTs will no longer both succeed —
    the second one sees rowcount=0 and we reply with 409 (or 404 if the
    teacher actually doesn't exist)."""
    normalized = normalize_courses_input(body.courses)
    if not normalized:
        raise HTTPException(status_code=400, detail="Courses cannot be empty.")
    with get_conn() as conn:
        updated = conn.execute(
            """UPDATE teachers
               SET courses = ?
               WHERE id = ? AND is_visible = 1
                 AND (courses IS NULL OR TRIM(courses) = '')""",
            (normalized, teacher_id),
        ).rowcount
        if updated == 0:
            # Distinguish "no such teacher" from "already set"
            exists = conn.execute(
                "SELECT 1 FROM teachers WHERE id = ? AND is_visible = 1",
                (teacher_id,),
            ).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Teacher not found")
            raise HTTPException(status_code=409, detail="Courses already set for this teacher.")
    return {"ok": True, "courses": parse_courses(normalized)}


@app.post("/api/teachers/submit")
def submit_teacher(body: TeacherSubmitIn, request: Request):
    ip = client_ip(request)
    if not verify_turnstile(body.turnstile_token, ip):
        raise SpamError("captcha_failed", "Captcha verification failed. Refresh and try again.", status=400)
    iph = hash_ip(ip)
    sub_id = str(uuid.uuid4())
    courses_norm = normalize_courses_input(body.courses)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO teacher_submissions (id, name, subject, courses, ip_hash, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (sub_id, body.name.strip(), (body.subject or "").strip() or None, courses_norm, iph),
        )
    return {"ok": True, "id": sub_id}


@app.post("/api/suggestions")
def post_suggestion(body: SuggestionIn, request: Request):
    """Public write-only endpoint. Reads are admin-only.

    Users can send site feedback here — bug reports, missing teachers,
    feature ideas. Rate-limited to 3/day per ip_hash with the same
    Turnstile + duplicate-body protection as reviews.
    """
    ip = client_ip(request)
    if not verify_turnstile(body.turnstile_token, ip):
        raise SpamError("captcha_failed", "Captcha verification failed. Refresh and try again.", status=400)
    cleaned = check_suggestion(body.body)
    iph = hash_ip(ip)
    enforce_suggestion_rate_limit(iph, cleaned)
    sug_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO suggestions (id, body, ip_hash) VALUES (?, ?, ?)",
            (sug_id, cleaned, iph),
        )
    return {"ok": True, "id": sug_id}


# ——— Admin

def require_admin(authorization: Optional[str]):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin token")
    token = authorization.split(" ", 1)[1].strip()
    if token not in ADMIN_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@app.get("/api/admin/submissions")
def admin_list_submissions(authorization: Optional[str] = Header(default=None)):
    require_admin(authorization)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, subject, courses, status, created_at FROM teacher_submissions WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["courses"] = parse_courses(d.get("courses"))
        out.append(d)
    return out


@app.post("/api/admin/submissions/{sub_id}/approve")
def admin_approve(sub_id: str, authorization: Optional[str] = Header(default=None)):
    require_admin(authorization)
    with get_conn() as conn:
        sub = conn.execute(
            "SELECT id, name, subject, courses FROM teacher_submissions WHERE id = ? AND status = 'pending'",
            (sub_id,),
        ).fetchone()
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found or already handled")
        teacher_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO teachers (id, name, subject, courses) VALUES (?, ?, ?, ?)",
            (teacher_id, sub["name"], sub["subject"], sub["courses"]),
        )
        conn.execute(
            "UPDATE teacher_submissions SET status = 'approved' WHERE id = ?",
            (sub_id,),
        )
    return {"ok": True, "teacher_id": teacher_id}


@app.post("/api/admin/submissions/{sub_id}/reject")
def admin_reject(sub_id: str, authorization: Optional[str] = Header(default=None)):
    require_admin(authorization)
    with get_conn() as conn:
        n = conn.execute(
            "UPDATE teacher_submissions SET status = 'rejected' WHERE id = ? AND status = 'pending'",
            (sub_id,),
        ).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="Submission not found or already handled")
    return {"ok": True}


@app.post("/api/admin/teachers/{teacher_id}/courses/clear")
def admin_clear_courses(teacher_id: str, authorization: Optional[str] = Header(default=None)):
    require_admin(authorization)
    with get_conn() as conn:
        n = conn.execute(
            "UPDATE teachers SET courses = NULL WHERE id = ?", (teacher_id,)
        ).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return {"ok": True}


@app.post("/api/admin/reviews/{review_id}/hide")
def admin_hide_review(review_id: str, authorization: Optional[str] = Header(default=None)):
    require_admin(authorization)
    with get_conn() as conn:
        n = conn.execute(
            "UPDATE reviews SET is_visible = 0 WHERE id = ?", (review_id,)
        ).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"ok": True}


@app.post("/api/admin/reviews/{review_id}/unhide")
def admin_unhide_review(review_id: str, authorization: Optional[str] = Header(default=None)):
    """Reversibility for hide. Used when a hide was a mistake — admin
    sees a hidden row in the browse list and clicks Unhide to restore it."""
    require_admin(authorization)
    with get_conn() as conn:
        n = conn.execute(
            "UPDATE reviews SET is_visible = 1 WHERE id = ?", (review_id,)
        ).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"ok": True}


@app.get("/api/admin/reviews")
def admin_list_reviews(
    authorization: Optional[str] = Header(default=None),
    q: Optional[str] = Query(default=None, max_length=100),
    teacher_id: Optional[str] = Query(default=None, max_length=100),
    include_hidden: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Browse-and-hide for the admin Tools tab. The UI is a two-level
    drill-down: list teachers, then click a teacher to manage their
    reviews. Pass `teacher_id` to scope to one teacher's reviews;
    omit it for the unscoped firehose (useful for global comment search).

    `q` matches teacher name OR comment text (case-insensitive substring)
    when no teacher_id is set. With teacher_id, q matches comment text only
    so the admin can search WITHIN that teacher's reviews.
    `include_hidden=True` by default so admin can find what they hid and
    unhide if needed. Newest first."""
    require_admin(authorization)
    where = []
    params = []
    if not include_hidden:
        where.append("r.is_visible = 1")
    if teacher_id:
        where.append("r.teacher_id = ?")
        params.append(teacher_id)
    if q:
        like = f"%{q.lower()}%"
        if teacher_id:
            # Scoped: search comment only — name is implied by the drill-down.
            where.append("LOWER(COALESCE(r.comment, '')) LIKE ?")
            params.append(like)
        else:
            where.append("(LOWER(t.name) LIKE ? OR LOWER(COALESCE(r.comment, '')) LIKE ?)")
            params.extend([like, like])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
      SELECT r.id, r.teaching_quality, r.test_difficulty, r.homework_load,
             r.easygoingness, r.would_take_again, r.comment, r.created_at,
             r.is_visible,
             t.id AS teacher_id, t.name AS teacher_name, t.subject AS teacher_subject
      FROM reviews r
      JOIN teachers t ON t.id = r.teacher_id
      {where_sql}
      ORDER BY r.created_at DESC
      LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {
        "reviews": [
            {
                "id": r["id"],
                "teaching_quality": r["teaching_quality"],
                "test_difficulty": r["test_difficulty"],
                "homework_load": r["homework_load"],
                "easygoingness": r["easygoingness"],
                "would_take_again": r["would_take_again"],
                "comment": r["comment"],
                "created_at": r["created_at"],
                "is_visible": bool(r["is_visible"]),
                "teacher_id": r["teacher_id"],
                "teacher_name": r["teacher_name"],
                "teacher_subject": r["teacher_subject"],
            }
            for r in rows
        ],
        "has_more": len(rows) == limit,
    }


@app.get("/api/admin/suggestions")
def admin_list_suggestions(
    include_resolved: bool = Query(default=False),
    authorization: Optional[str] = Header(default=None),
):
    require_admin(authorization)
    sql = "SELECT id, body, created_at, is_resolved, resolved_at FROM suggestions"
    if not include_resolved:
        sql += " WHERE is_resolved = 0"
    sql += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/suggestions/{sug_id}/resolve")
def admin_resolve_suggestion(sug_id: str, authorization: Optional[str] = Header(default=None)):
    require_admin(authorization)
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        n = conn.execute(
            "UPDATE suggestions SET is_resolved = 1, resolved_at = ? WHERE id = ? AND is_resolved = 0",
            (now, sug_id),
        ).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="Suggestion not found or already resolved")
    return {"ok": True}


@app.post("/api/admin/suggestions/{sug_id}/reopen")
def admin_reopen_suggestion(sug_id: str, authorization: Optional[str] = Header(default=None)):
    require_admin(authorization)
    with get_conn() as conn:
        n = conn.execute(
            "UPDATE suggestions SET is_resolved = 0, resolved_at = NULL WHERE id = ? AND is_resolved = 1",
            (sug_id,),
        ).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="Suggestion not found or not resolved")
    return {"ok": True}


@app.post("/api/admin/teachers/{teacher_id}/edit")
def admin_edit_teacher(
    teacher_id: str,
    body: TeacherEditIn,
    authorization: Optional[str] = Header(default=None),
):
    """Admin-only rename + subject change. Only fields actually provided
    in the body get updated, so editing just the name leaves the subject
    alone (and vice versa). Returns the post-update row so the UI can
    reflect the change without a re-fetch."""
    require_admin(authorization)
    name = body.name.strip() if body.name is not None else None
    subject = body.subject.strip() if body.subject is not None else None
    if name is None and subject is None:
        raise HTTPException(status_code=400, detail="Provide at least one of: name, subject")
    if name == "":
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    sets = []
    params: list = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if subject is not None:
        # Empty string for subject means "clear it" — distinguishes from
        # "didn't touch it" (None). Stored as NULL so the UI shows "—".
        sets.append("subject = ?")
        params.append(subject if subject else None)
    params.append(teacher_id)

    with get_conn() as conn:
        n = conn.execute(
            f"UPDATE teachers SET {', '.join(sets)} WHERE id = ?",
            params,
        ).rowcount
        if not n:
            raise HTTPException(status_code=404, detail="Teacher not found")
        row = conn.execute(
            "SELECT id, name, subject, courses, is_visible FROM teachers WHERE id = ?",
            (teacher_id,),
        ).fetchone()
    return {
        "id": row["id"],
        "name": row["name"],
        "subject": row["subject"],
        "courses": parse_courses(row["courses"]),
        "is_visible": bool(row["is_visible"]),
    }


@app.get("/api/admin/stats")
def admin_stats(authorization: Optional[str] = Header(default=None)):
    """Lightweight breakdown of the review + teacher tables. Useful for
    answering "how many imports vs. native reviews do we have right now"
    without needing shell access to the Railway volume."""
    require_admin(authorization)
    with get_conn() as conn:
        rev_total = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
        rev_visible = conn.execute(
            "SELECT COUNT(*) AS n FROM reviews WHERE is_visible = 1"
        ).fetchone()["n"]
        rev_by_source = conn.execute(
            """SELECT source, is_visible, COUNT(*) AS n
               FROM reviews GROUP BY source, is_visible"""
        ).fetchall()
        teach_total = conn.execute("SELECT COUNT(*) AS n FROM teachers").fetchone()["n"]
        teach_visible = conn.execute(
            "SELECT COUNT(*) AS n FROM teachers WHERE is_visible = 1"
        ).fetchone()["n"]
    # Fold the (source, is_visible) cross-tab into a flat dict per source.
    by_source: dict = {}
    for r in rev_by_source:
        bucket = by_source.setdefault(r["source"], {"visible": 0, "hidden": 0, "total": 0})
        if r["is_visible"]:
            bucket["visible"] += r["n"]
        else:
            bucket["hidden"] += r["n"]
        bucket["total"] += r["n"]
    return {
        "reviews": {
            "total": rev_total,
            "visible": rev_visible,
            "hidden": rev_total - rev_visible,
            "by_source": by_source,
        },
        "teachers": {"total": teach_total, "visible": teach_visible},
    }


class DeleteBySourceIn(BaseModel):
    """Bulk-delete reviews by source. Allowed sources are the imported and
    AI-generated buckets — never `user` (those are real submissions and
    must be protected from accidental wipe via this endpoint)."""
    source: str
    dry_run: bool = True


@app.post("/api/admin/delete-reviews-by-source")
def admin_delete_reviews_by_source(
    body: DeleteBySourceIn, authorization: Optional[str] = Header(default=None),
):
    """Wipe every review with the given source. Native `user` reviews are
    explicitly NOT allowed through this endpoint — they're real student
    submissions and require a more deliberate path to delete. dry_run
    returns the count without touching anything."""
    require_admin(authorization)
    if body.source not in ("imported_biph_insights", "ai_generated"):
        raise HTTPException(
            status_code=400,
            detail="source must be 'imported_biph_insights' or 'ai_generated'. "
                   "Native 'user' reviews can't be bulk-deleted through this route.",
        )
    with get_conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM reviews WHERE source = ?", (body.source,),
        ).fetchone()["n"]
        if body.dry_run:
            return {"dry_run": True, "would_delete": n, "source": body.source}
        deleted = conn.execute(
            "DELETE FROM reviews WHERE source = ?", (body.source,),
        ).rowcount
    return {"dry_run": False, "deleted": deleted, "source": body.source}


class RegenIn(BaseModel):
    """Input to the regenerate-reviews flow. Source-agnostic — a re-run that
    refreshes the AI-generated corpus passes source='ai_generated', the
    initial run from base44 passed source='imported_biph_insights'. dry_run
    previews without writing."""
    target_total: int = Field(default=1000, ge=10, le=5000)
    dry_run: bool = True
    seed: Optional[int] = None
    source: str = Field(default="imported_biph_insights")


@app.post("/api/admin/regenerate-reviews")
def admin_regenerate_reviews(
    body: RegenIn, authorization: Optional[str] = Header(default=None),
):
    """Replace all base44-imported reviews with mechanically-generated ones.

    Steps when dry_run=False:
      1. Pull every row where source='imported_biph_insights' (the corpus).
      2. Generate `target_total` new reviews using regen.generate_reviews,
         sampled per-teacher from each teacher's own ratings + sentence pool.
      3. In ONE transaction: DELETE all base44 rows, INSERT all generated
         rows. Either both succeed or neither — no half-state.
      4. Return summary counts + corpus snapshot (for offline backup).

    Why corpus is in the response body (not a file): Railway's container
    filesystem is ephemeral and volume-mount paths shouldn't be polluted
    with one-time backups. Caller pipes the response to a local JSON file
    and stores it wherever they want."""
    require_admin(authorization)
    from . import regen

    if body.source not in ("imported_biph_insights", "ai_generated"):
        raise HTTPException(
            status_code=400,
            detail="source must be 'imported_biph_insights' or 'ai_generated'",
        )

    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT id, teacher_id, teaching_quality, test_difficulty,
                      homework_load, easygoingness, would_take_again, comment,
                      created_at, source
               FROM reviews WHERE source = ?""",
            (body.source,),
        ).fetchall()]

        if not rows:
            raise HTTPException(
                status_code=400,
                detail=f"No reviews with source='{body.source}' — nothing to regenerate from",
            )

        # Pull teacher subjects so the generator can add subject-specific
        # lexical texture ("essay 反馈很认真" only on English teachers, etc.).
        teacher_subjects = {
            r["id"]: r["subject"]
            for r in conn.execute("SELECT id, subject FROM teachers").fetchall()
        }
        generated = regen.generate_reviews(
            rows, body.target_total, seed=body.seed,
            teacher_subjects=teacher_subjects,
        )
        plan = regen.plan_per_teacher(
            regen._build_per_teacher_corpus(rows, teacher_subjects=teacher_subjects),
            body.target_total,
        )

        if body.dry_run:
            return {
                "dry_run": True,
                "would_delete": len(rows),
                "would_generate": len(generated),
                "per_teacher_plan": plan,
                "sample_generated": generated[:3],
                "corpus_size": len(rows),
            }

        # Execute. The `with get_conn() as conn:` block already wraps this in
        # an implicit transaction — if any INSERT below raises, the DELETE
        # gets rolled back automatically.
        n_deleted = conn.execute(
            "DELETE FROM reviews WHERE source = ?", (body.source,),
        ).rowcount
        for g in generated:
            conn.execute(
                """INSERT INTO reviews
                   (id, teacher_id, teaching_quality, test_difficulty,
                    homework_load, easygoingness, would_take_again, comment,
                    ip_hash, source, legacy_id, is_visible, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    g["id"], g["teacher_id"],
                    g["teaching_quality"], g["test_difficulty"],
                    g["homework_load"], g["easygoingness"],
                    g["would_take_again"], g["comment"],
                    g["ip_hash"], g["source"], g["legacy_id"],
                    g["is_visible"], g["created_at"],
                ),
            )

    return {
        "dry_run": False,
        "deleted": n_deleted,
        "generated": len(generated),
        "per_teacher_plan": plan,
        # Corpus echoed back so the caller can save the backup AFTER seeing
        # success. (If we failed mid-way, the response wouldn't include this
        # and the transaction would have rolled back — corpus still in DB.)
        "corpus_backup": rows,
    }


@app.post("/api/admin/sync-base44")
def admin_sync_base44(authorization: Optional[str] = Header(default=None)):
    """One-shot pull from the base44 reference site to pick up reviews
    students still post there. Idempotent via legacy_id, so re-running is
    safe — only new rows get inserted. Returns before/after counts so the
    caller can see what changed."""
    require_admin(authorization)
    from .seed import sync_from_base44
    try:
        return sync_from_base44()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"base44 sync failed: {e}")


# ——— Static frontend (single-origin hosting, no CORS headache for v1)
#
# Why the custom subclass: the default StaticFiles sets no Cache-Control header
# on JS/CSS/HTML, so browsers apply heuristic caching and hold stale copies of
# app.js for hours after a deploy. Users then see "the change isn't live" even
# though the file on disk is current. We force `no-cache` on text assets so the
# browser ALWAYS revalidates — etag/last-modified make this a fast 304 round
# trip when nothing changed, and a 200 with fresh bytes when it did. Images
# (PNG/SVG/ICO/WebP) keep aggressive caching because they almost never change.
class NoCacheStaticFiles(StaticFiles):
    REVALIDATE_EXTS = {".html", ".js", ".css", ".json", ".map"}
    LONG_CACHE_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".ico", ".webp", ".gif", ".woff", ".woff2"}

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        ext = Path(path).suffix.lower()
        if ext in self.REVALIDATE_EXTS:
            # Browser may cache, but MUST revalidate via etag before reuse.
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif ext in self.LONG_CACHE_EXTS:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


if FRONTEND_DIR.is_dir():
    app.mount("/", NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
