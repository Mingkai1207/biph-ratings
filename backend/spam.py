from __future__ import annotations

import hashlib
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .db import get_conn

TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "1x0000000000000000000000000000000AA")  # test key
IP_HASH_SALT = os.environ.get("IP_HASH_SALT", "biph-dev-salt")
TURNSTILE_ENABLED = os.environ.get("TURNSTILE_ENABLED", "1") == "1"

MAX_REVIEWS_PER_DAY = 5
TEACHER_COOLDOWN_DAYS = 7
MIN_COMMENT_LEN = 20
MAX_COMMENT_LEN = 2000
MAX_SUGGESTIONS_PER_DAY = 3
MIN_SUGGESTION_LEN = 10
MAX_SUGGESTION_LEN = 2000


class SpamError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status


def hash_ip(ip: str) -> str:
    return hashlib.sha256(f"{IP_HASH_SALT}:{ip}".encode()).hexdigest()


def verify_turnstile(token: str | None, remoteip: str | None = None) -> bool:
    if not TURNSTILE_ENABLED:
        return True
    if not token:
        return False
    data = {"secret": TURNSTILE_SECRET, "response": token}
    if remoteip:
        data["remoteip"] = remoteip
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=body,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            import json
            result = json.loads(resp.read().decode())
            return bool(result.get("success"))
    except Exception:
        return False


def check_comment(comment: str | None) -> str | None:
    if comment is None:
        return None
    c = comment.strip()
    if not c:
        return None
    if len(c) > MAX_COMMENT_LEN:
        raise SpamError("comment_too_long", f"Comment must be under {MAX_COMMENT_LEN} characters.")
    return c


def enforce_rate_limit(ip_hash: str, teacher_id: str, comment: str | None):
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(days=1)).isoformat()
    cooldown_start = (now - timedelta(days=TEACHER_COOLDOWN_DAYS)).isoformat()
    with get_conn() as conn:
        # Per-day cap
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM reviews WHERE ip_hash = ? AND created_at > ?",
            (ip_hash, day_ago),
        ).fetchone()
        if row["n"] >= MAX_REVIEWS_PER_DAY:
            raise SpamError(
                "rate_limited",
                f"You've posted {MAX_REVIEWS_PER_DAY} reviews today — come back tomorrow.",
                status=429,
            )
        # Per-teacher cooldown
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM reviews WHERE ip_hash = ? AND teacher_id = ? AND created_at > ?",
            (ip_hash, teacher_id, cooldown_start),
        ).fetchone()
        if row["n"] > 0:
            raise SpamError(
                "teacher_cooldown",
                f"You already reviewed this teacher within the last {TEACHER_COOLDOWN_DAYS} days.",
                status=429,
            )
        # Duplicate comment text
        if comment:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM reviews WHERE ip_hash = ? AND comment = ?",
                (ip_hash, comment),
            ).fetchone()
            if row["n"] > 0:
                raise SpamError("duplicate", "You already posted that comment.")


def check_suggestion(body: str | None) -> str:
    if body is None:
        raise SpamError("suggestion_too_short", f"Write at least {MIN_SUGGESTION_LEN} characters.")
    b = body.strip()
    if len(b) < MIN_SUGGESTION_LEN:
        raise SpamError("suggestion_too_short", f"Write at least {MIN_SUGGESTION_LEN} characters.")
    if len(b) > MAX_SUGGESTION_LEN:
        raise SpamError("suggestion_too_long", f"Suggestion must be under {MAX_SUGGESTION_LEN} characters.")
    return b


def enforce_suggestion_rate_limit(ip_hash: str, body: str):
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(days=1)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM suggestions WHERE ip_hash = ? AND created_at > ?",
            (ip_hash, day_ago),
        ).fetchone()
        if row["n"] >= MAX_SUGGESTIONS_PER_DAY:
            raise SpamError(
                "rate_limited",
                f"You've posted {MAX_SUGGESTIONS_PER_DAY} suggestions today — come back tomorrow.",
                status=429,
            )
        # Duplicate body — same person re-submitting the same text
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM suggestions WHERE ip_hash = ? AND body = ?",
            (ip_hash, body),
        ).fetchone()
        if row["n"] > 0:
            raise SpamError("duplicate", "You already sent that suggestion.")
