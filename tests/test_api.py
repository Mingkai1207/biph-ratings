"""
Tests for the public read endpoints. No turnstile, no auth required.

Focus: behavior verification — what the endpoints return, not just that
they don't crash. Every assertion is about real content or real shape.
"""


def test_health_returns_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_teachers_list_includes_seeded_teacher(client, seeded_teacher):
    r = client.get("/api/teachers")
    assert r.status_code == 200
    payload = r.json()
    assert isinstance(payload, list)
    ids = [t["id"] for t in payload]
    assert seeded_teacher in ids
    me = next(t for t in payload if t["id"] == seeded_teacher)
    assert me["name"] == "Test Teacher"
    assert me["subject"] == "Math"
    # A brand-new teacher has no reviews yet.
    assert me["review_count"] == 0


def test_teacher_detail_computes_averages(client, seeded_teacher_with_reviews):
    r = client.get(f"/api/teachers/{seeded_teacher_with_reviews}")
    assert r.status_code == 200
    data = r.json()
    assert data["review_count"] == 3
    # Fixture inserts tq=(5,4,5) -> avg 4.67; td=(3,3,2) -> 2.67;
    # hl=(2,3,2) -> 2.33; eg=(4,4,5) -> 4.33. Round to 2dp for tolerance.
    assert round(data["avg_teaching_quality"], 2) == 4.67
    assert round(data["avg_test_difficulty"], 2) == 2.67
    assert round(data["avg_homework_load"], 2) == 2.33
    assert round(data["avg_easygoingness"], 2) == 4.33


def test_teacher_detail_404_for_missing_id(client):
    r = client.get("/api/teachers/does-not-exist")
    assert r.status_code == 404


def test_card_png_renders_for_known_teacher(client, seeded_teacher_with_reviews):
    """Recent commit 876f21d redesigned this layout. Test it still renders
    PNG bytes with the right content-type and cache header."""
    r = client.get(f"/api/teachers/{seeded_teacher_with_reviews}/card.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # PNG magic number: first 8 bytes are 89 50 4E 47 0D 0A 1A 0A
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    # Non-trivial size — a blank canvas would be under 10KB; a real card
    # with stats + QR is 30KB+.
    assert len(r.content) > 10_000
    assert "max-age" in r.headers.get("cache-control", "")


def test_qr_png_renders_for_known_teacher(client, seeded_teacher):
    """Recent commit 2e40aa8 added this endpoint. Bulk-print page depends
    on it returning a scannable PNG for every visible teacher."""
    r = client.get(f"/api/teachers/{seeded_teacher}/qr.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(r.content) > 500  # QR codes are small but not empty


def test_card_png_404_for_missing_teacher(client):
    r = client.get("/api/teachers/does-not-exist/card.png")
    assert r.status_code == 404


def test_qr_png_404_for_missing_teacher(client):
    r = client.get("/api/teachers/does-not-exist/qr.png")
    assert r.status_code == 404


# ——— Admin teacher edit (rename / subject change)

ADMIN_HEADERS = {"Authorization": "Bearer test-admin-token"}


def test_admin_edit_teacher_rejects_unauthorized(client, seeded_teacher):
    r = client.post(f"/api/admin/teachers/{seeded_teacher}/edit", json={"name": "New"})
    assert r.status_code == 401


def test_admin_edit_teacher_renames(client, seeded_teacher):
    r = client.post(
        f"/api/admin/teachers/{seeded_teacher}/edit",
        json={"name": "Renamed Teacher"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Teacher"
    # Subject was untouched on this edit, so it stays as the seeded value.
    assert r.json()["subject"] == "Math"


def test_admin_edit_teacher_changes_subject_only(client, seeded_teacher):
    r = client.post(
        f"/api/admin/teachers/{seeded_teacher}/edit",
        json={"subject": "Physics"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Test Teacher"  # name preserved
    assert r.json()["subject"] == "Physics"


def test_admin_edit_teacher_clears_subject_on_empty_string(client, seeded_teacher):
    r = client.post(
        f"/api/admin/teachers/{seeded_teacher}/edit",
        json={"subject": ""},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["subject"] is None


def test_admin_edit_teacher_404_for_missing(client):
    r = client.post(
        "/api/admin/teachers/does-not-exist/edit",
        json={"name": "Anyone"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 404


def test_admin_edit_teacher_rejects_empty_body(client, seeded_teacher):
    r = client.post(
        f"/api/admin/teachers/{seeded_teacher}/edit",
        json={},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


def test_admin_edit_teacher_rejects_too_short_name(client, seeded_teacher):
    r = client.post(
        f"/api/admin/teachers/{seeded_teacher}/edit",
        json={"name": "A"},  # min_length=2
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 422


# ——— Static-asset cache headers
#
# Why these tests exist: a previous deploy shipped the right app.js but users
# kept seeing stale code because the default StaticFiles set no Cache-Control,
# so browsers held cached copies for hours. We now force `no-cache` on JS/CSS/
# HTML and aggressive caching on images. These tests pin that contract so
# nobody accidentally regresses it.


def test_app_js_has_revalidate_cache_header(client):
    r = client.get("/app.js")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", "")


def test_styles_css_has_revalidate_cache_header(client):
    r = client.get("/styles.css")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", "")


def test_index_html_has_revalidate_cache_header(client):
    r = client.get("/index.html")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", "")


# ——— Admin browse-and-hide reviews
#
# The Tools tab used to take a UUID-paste — the admin had no way to see what
# they were hiding. New flow: GET /api/admin/reviews returns reviews joined
# with teacher info so the UI can render a browseable list, then the existing
# hide endpoint + a new unhide endpoint flip visibility in either direction.


def _seed_review(teacher_id, comment="ok", visible=True):
    """Helper: insert one review on the given teacher and return its id."""
    import uuid as _uuid
    from backend import db as _db
    rid = _uuid.uuid4().hex
    with _db.get_conn() as conn:
        conn.execute(
            "INSERT INTO reviews (id, teacher_id, teaching_quality, "
            "test_difficulty, homework_load, easygoingness, comment, "
            "is_visible) VALUES (?, ?, 5, 3, 2, 4, ?, ?)",
            (rid, teacher_id, comment, 1 if visible else 0),
        )
    return rid


def test_admin_list_reviews_requires_auth(client):
    r = client.get("/api/admin/reviews")
    assert r.status_code == 401


def test_admin_list_reviews_returns_teacher_info(client, seeded_teacher):
    rid = _seed_review(seeded_teacher, comment="great class")
    r = client.get("/api/admin/reviews", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    rows = r.json()["reviews"]
    mine = next((x for x in rows if x["id"] == rid), None)
    assert mine is not None
    assert mine["teacher_name"] == "Test Teacher"
    assert mine["teacher_subject"] == "Math"
    assert mine["teacher_id"] == seeded_teacher
    assert mine["comment"] == "great class"
    assert mine["is_visible"] is True


def test_admin_list_reviews_includes_hidden_by_default(client, seeded_teacher):
    rid = _seed_review(seeded_teacher, comment="hidden review", visible=False)
    r = client.get("/api/admin/reviews", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["reviews"]]
    assert rid in ids
    me = next(x for x in r.json()["reviews"] if x["id"] == rid)
    assert me["is_visible"] is False


def test_admin_list_reviews_can_exclude_hidden(client, seeded_teacher):
    rid = _seed_review(seeded_teacher, comment="hidden review", visible=False)
    r = client.get(
        "/api/admin/reviews?include_hidden=false", headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["reviews"]]
    assert rid not in ids


def test_admin_list_reviews_filters_by_teacher_name(client, seeded_teacher):
    """`q` must match teacher name (case-insensitive substring)."""
    rid = _seed_review(seeded_teacher, comment="something")
    r = client.get("/api/admin/reviews?q=test+teach", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert any(x["id"] == rid for x in r.json()["reviews"])


def test_admin_list_reviews_filters_by_comment_text(client, seeded_teacher):
    rid = _seed_review(seeded_teacher, comment="UNIQUE_NEEDLE_42")
    r = client.get("/api/admin/reviews?q=UNIQUE_NEEDLE", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    rows = r.json()["reviews"]
    assert len(rows) == 1
    assert rows[0]["id"] == rid


def test_admin_list_reviews_pagination(client, seeded_teacher):
    """Pin the limit/offset contract — the admin UI's Load More relies on it."""
    for i in range(3):
        _seed_review(seeded_teacher, comment=f"page {i}")
    page1 = client.get(
        "/api/admin/reviews?limit=2&offset=0", headers=ADMIN_HEADERS,
    ).json()
    page2 = client.get(
        "/api/admin/reviews?limit=2&offset=2", headers=ADMIN_HEADERS,
    ).json()
    assert len(page1["reviews"]) == 2
    page1_ids = {x["id"] for x in page1["reviews"]}
    page2_ids = {x["id"] for x in page2["reviews"]}
    assert page1_ids.isdisjoint(page2_ids)


def test_admin_unhide_review_requires_auth(client, seeded_teacher):
    rid = _seed_review(seeded_teacher, visible=False)
    r = client.post(f"/api/admin/reviews/{rid}/unhide")
    assert r.status_code == 401


def test_admin_unhide_review_restores_visibility(client, seeded_teacher):
    rid = _seed_review(seeded_teacher, visible=False)
    r = client.post(
        f"/api/admin/reviews/{rid}/unhide", headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    # And it must show up in the public reviews list now.
    public = client.get(f"/api/teachers/{seeded_teacher}/reviews").json()
    assert any(x["id"] == rid for x in public["reviews"])


def test_admin_unhide_review_404_for_missing(client):
    r = client.post(
        "/api/admin/reviews/does-not-exist/unhide", headers=ADMIN_HEADERS,
    )
    assert r.status_code == 404


# ——— Drill-down: GET /api/admin/reviews?teacher_id=...
#
# The Tools tab drills from teacher list → that teacher's reviews. The
# `teacher_id` query param scopes the result. With a teacher_id set, `q`
# narrows to comment text only (teacher name is implicit at that level).


def test_admin_list_reviews_filters_by_teacher_id(client, seeded_teacher):
    """Other teachers' reviews must not leak into a scoped query."""
    import uuid as _uuid
    from backend import db as _db
    other_id = _uuid.uuid4().hex
    with _db.get_conn() as conn:
        conn.execute(
            "INSERT INTO teachers (id, name, subject, is_visible) "
            "VALUES (?, 'Other Teacher', 'Physics', 1)",
            (other_id,),
        )
    mine = _seed_review(seeded_teacher, comment="for me")
    theirs = _seed_review(other_id, comment="for them")
    r = client.get(
        f"/api/admin/reviews?teacher_id={seeded_teacher}", headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()["reviews"]}
    assert mine in ids
    assert theirs not in ids


def test_admin_list_reviews_teacher_id_with_comment_search(client, seeded_teacher):
    """Inside a teacher drill-down, q narrows to comment text only."""
    keep = _seed_review(seeded_teacher, comment="contains FINDME marker")
    drop = _seed_review(seeded_teacher, comment="other content")
    r = client.get(
        f"/api/admin/reviews?teacher_id={seeded_teacher}&q=FINDME",
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()["reviews"]}
    assert keep in ids
    assert drop not in ids


def test_admin_list_reviews_teacher_id_unknown_returns_empty(client):
    r = client.get(
        "/api/admin/reviews?teacher_id=does-not-exist", headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["reviews"] == []


# ——— Author revoke window
#
# After submission, the author has REVOKE_WINDOW_SECONDS to take their review
# back (oops-undo, not edit). Verified by ip_hash match — no random caller
# can delete a stranger's review even if they have the id. The teacher-detail
# response also includes the review id + window so the UI can show a countdown.


def _seed_review_with_ip(teacher_id, ip_hash, age_seconds=0, comment="ok"):
    """Insert a review attributed to a given ip_hash and aged by N seconds.
    Used to simulate "you just posted" vs "you posted 2 minutes ago"."""
    import uuid as _uuid
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from backend import db as _db
    rid = _uuid.uuid4().hex
    when = _dt.now(_tz.utc) - _td(seconds=age_seconds)
    # Match sqlite default format: 'YYYY-MM-DD HH:MM:SS'
    when_sql = when.strftime("%Y-%m-%d %H:%M:%S")
    with _db.get_conn() as conn:
        conn.execute(
            "INSERT INTO reviews (id, teacher_id, teaching_quality, "
            "test_difficulty, homework_load, easygoingness, comment, "
            "ip_hash, is_visible, created_at) "
            "VALUES (?, ?, 5, 3, 2, 4, ?, ?, 1, ?)",
            (rid, teacher_id, comment, ip_hash, when_sql),
        )
    return rid


def _my_ip_hash():
    """Starlette's TestClient reports `host='testclient'` (literal string),
    not 127.0.0.1. So the server hashes 'testclient' as the IP for every
    request — match that here so the revoke auth check sees the request
    as coming from the review's author."""
    from backend.spam import hash_ip
    return hash_ip("testclient")


def test_revoke_review_succeeds_within_window(client, seeded_teacher):
    rid = _seed_review_with_ip(seeded_teacher, _my_ip_hash(), age_seconds=5)
    r = client.post(f"/api/reviews/{rid}/revoke")
    assert r.status_code == 200
    # And the review actually disappears from the public list.
    listed = client.get(f"/api/teachers/{seeded_teacher}/reviews").json()
    assert all(x["id"] != rid for x in listed["reviews"])


def test_revoke_review_rejects_after_window(client, seeded_teacher):
    """61 seconds old: window closed, must return 410."""
    rid = _seed_review_with_ip(seeded_teacher, _my_ip_hash(), age_seconds=61)
    r = client.post(f"/api/reviews/{rid}/revoke")
    assert r.status_code == 410
    # Still in the DB.
    listed = client.get(f"/api/teachers/{seeded_teacher}/reviews").json()
    assert any(x["id"] == rid for x in listed["reviews"])


def test_revoke_review_rejects_wrong_ip(client, seeded_teacher):
    """Review owned by some other ip_hash — current caller can't touch it."""
    rid = _seed_review_with_ip(
        seeded_teacher, ip_hash="not-the-callers-hash", age_seconds=5,
    )
    r = client.post(f"/api/reviews/{rid}/revoke")
    assert r.status_code == 403


def test_revoke_review_404_for_unknown_id(client):
    r = client.post("/api/reviews/does-not-exist/revoke")
    assert r.status_code == 404


def test_teacher_detail_includes_review_id_and_revoke_window(client, seeded_teacher):
    """The UI needs both to render the countdown button. Pin the contract."""
    rid = _seed_review_with_ip(seeded_teacher, _my_ip_hash(), age_seconds=5)
    r = client.get(f"/api/teachers/{seeded_teacher}")
    assert r.status_code == 200
    mr = r.json()["my_recent_review"]
    assert mr is not None
    assert mr["id"] == rid
    assert mr["revoke_window_seconds"] == 60


# ——— Multi-token admin auth
#
# We support a primary ADMIN_TOKEN plus an additional comma-separated
# ADMIN_TOKENS list so multiple humans can have their own credentials
# without sharing one. require_admin must accept any token from either
# source (and reject everything else).


def test_admin_accepts_multiple_tokens(client, seeded_teacher, monkeypatch):
    """A token in ADMIN_TOKENS authenticates the same as ADMIN_TOKEN."""
    import backend.main as _m
    monkeypatch.setattr(_m, "ADMIN_TOKENS", {"primary-tok", "secondary-tok"})
    # Both tokens succeed.
    for tok in ("primary-tok", "secondary-tok"):
        r = client.post(
            f"/api/admin/teachers/{seeded_teacher}/edit",
            json={"name": "Renamed via " + tok},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, f"token {tok} should be accepted"
    # An unrelated token still fails.
    r = client.post(
        f"/api/admin/teachers/{seeded_teacher}/edit",
        json={"name": "Should not stick"},
        headers={"Authorization": "Bearer not-in-set"},
    )
    assert r.status_code == 401


def test_admin_token_parser_unions_both_env_vars(monkeypatch):
    """_parse_admin_tokens combines ADMIN_TOKEN (single) and ADMIN_TOKENS
    (comma-separated). Whitespace and empty entries are dropped."""
    import backend.main as _m
    monkeypatch.setenv("ADMIN_TOKEN", "alpha")
    monkeypatch.setenv("ADMIN_TOKENS", "beta, gamma ,, delta")
    got = _m._parse_admin_tokens()
    assert got == {"alpha", "beta", "gamma", "delta"}


def test_admin_token_parser_falls_back_to_dev_default(monkeypatch):
    """Neither env var set → dev-only default so local runs work."""
    import backend.main as _m
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_TOKENS", raising=False)
    assert _m._parse_admin_tokens() == {"dev-admin-token"}


# ——— Admin stats endpoint (count reviews / teachers / by-source breakdown)


def test_admin_stats_requires_auth(client):
    r = client.get("/api/admin/stats")
    assert r.status_code == 401


def test_admin_stats_returns_breakdown(client, seeded_teacher):
    """Stats endpoint must report total + visible/hidden + by-source bucket
    correctly. Seed two reviews of different sources and visibilities."""
    import uuid as _uuid
    from backend import db as _db
    with _db.get_conn() as conn:
        # 1 user review, visible
        conn.execute(
            "INSERT INTO reviews (id, teacher_id, teaching_quality, "
            "test_difficulty, homework_load, easygoingness, comment, "
            "is_visible, source) VALUES (?, ?, 5, 3, 2, 4, 'a', 1, 'user')",
            (_uuid.uuid4().hex, seeded_teacher),
        )
        # 1 imported review, hidden
        conn.execute(
            "INSERT INTO reviews (id, teacher_id, teaching_quality, "
            "test_difficulty, homework_load, easygoingness, comment, "
            "is_visible, source) VALUES (?, ?, 4, 4, 4, 4, 'b', 0, 'imported_biph_insights')",
            (_uuid.uuid4().hex, seeded_teacher),
        )
    r = client.get("/api/admin/stats", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["reviews"]["total"] >= 2
    assert "user" in data["reviews"]["by_source"]
    assert "imported_biph_insights" in data["reviews"]["by_source"]
    assert data["reviews"]["by_source"]["user"]["visible"] >= 1
    assert data["reviews"]["by_source"]["imported_biph_insights"]["hidden"] >= 1
