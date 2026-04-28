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

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Auto-sync interval. Default 24h; set BASE44_SYNC_INTERVAL_SEC=0 to disable
# (useful for tests + local dev where you don't want background HTTP traffic).
BASE44_SYNC_INTERVAL_SEC = int(os.environ.get("BASE44_SYNC_INTERVAL_SEC", "86400"))
# Wait this long after boot before the first sync, so a redeploy doesn't
# immediately hammer base44 every time we push code.
BASE44_SYNC_INITIAL_DELAY_SEC = int(os.environ.get("BASE44_SYNC_INITIAL_DELAY_SEC", "300"))

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
    except Exception:
        # Groq down / quota / parse failure — degrade to keyword search so
        # the UI doesn't dead-end. We still log the attempt for analytics.
        aisearch.log_search(iph, payload.query, None)
        teachers = list_teachers(q=payload.query, subject=None)
        return {
            "teachers": teachers,
            "explanation_en": "Smart search unavailable; showing keyword matches.",
            "explanation_zh": "智能搜索暂不可用；以下是关键词匹配结果。",
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
            """SELECT teaching_quality, test_difficulty, homework_load, easygoingness,
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
    if token != ADMIN_TOKEN:
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
