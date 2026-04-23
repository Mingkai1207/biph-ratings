import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, conint

from .db import get_conn, init_db
from .spam import (
    TEACHER_COOLDOWN_DAYS,
    SpamError,
    check_comment,
    enforce_rate_limit,
    hash_ip,
    verify_turnstile,
)

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

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


@app.exception_handler(SpamError)
async def spam_error_handler(request: Request, exc: SpamError):
    return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})


Rating = conint(ge=1, le=5)


class ReviewIn(BaseModel):
    teaching_quality: Rating
    test_difficulty: Rating
    homework_load: Rating
    easygoingness: Rating
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
    }


TEACHER_STATS_SELECT = """
    SELECT
      t.id, t.name, t.subject, t.courses,
      AVG(CASE WHEN r.is_visible = 1 THEN r.teaching_quality END) AS avg_tq,
      AVG(CASE WHEN r.is_visible = 1 THEN r.test_difficulty  END) AS avg_td,
      AVG(CASE WHEN r.is_visible = 1 THEN r.homework_load    END) AS avg_hl,
      AVG(CASE WHEN r.is_visible = 1 THEN r.easygoingness    END) AS avg_eg,
      COALESCE(SUM(CASE WHEN r.is_visible = 1 THEN 1 ELSE 0 END), 0) AS review_count
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
                      comment, created_at
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


@app.get("/api/teachers/{teacher_id}/reviews")
def list_reviews(
    teacher_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, teaching_quality, test_difficulty, homework_load, easygoingness,
                      comment, created_at
               FROM reviews
               WHERE teacher_id = ? AND is_visible = 1
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (teacher_id, limit, offset),
        ).fetchall()
    return {
        "reviews": [dict(r) for r in rows],
        "has_more": len(rows) == limit,
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
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO reviews
               (id, teacher_id, teaching_quality, test_difficulty, homework_load, easygoingness,
                comment, ip_hash, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'user')""",
            (
                review_id, teacher_id,
                body.teaching_quality, body.test_difficulty, body.homework_load, body.easygoingness,
                comment, iph,
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


# ——— Static frontend (single-origin hosting, no CORS headache for v1)
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
