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
