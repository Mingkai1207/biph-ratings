"""Word masking must not hide reviews, alter stored text or affect ratings."""
import uuid

import pytest

from backend import db


def insert_review(teacher_id, comment, *, source="user", visible=1):
    review_id = uuid.uuid4().hex
    with db.get_conn() as conn:
        conn.execute(
            """INSERT INTO reviews
               (id, teacher_id, teaching_quality, test_difficulty, homework_load,
                easygoingness, comment, source, legacy_id, is_visible)
               VALUES (?, ?, 4, 3, 2, 5, ?, ?, ?, ?)""",
            (review_id, teacher_id, comment, source,
             uuid.uuid4().hex if source == "base44" else None, visible),
        )
    return review_id


@pytest.mark.parametrize("source, comment, word", [
    ("user", "Useful notes; fucking difficult tests.", "fucking"),
    ("base44", "别骂傻逼，老师的讲义写得很清楚。", "傻逼"),
])
def test_existing_and_imported_reviews_get_metadata_without_data_changes(
    client, seeded_teacher, source, comment, word
):
    review_id = insert_review(seeded_teacher, comment, source=source)
    response = client.get(f"/api/teachers/{seeded_teacher}/reviews")
    assert response.status_code == 200
    review = response.json()["reviews"][0]
    assert review["id"] == review_id
    assert review["comment"] == comment
    assert [p["text"] for p in review["comment_segments"] if p["sensitive"]] == [word]
    assert "".join(p["text"] for p in review["comment_segments"]) == comment
    with db.get_conn() as conn:
        stored = conn.execute("SELECT comment, source, is_visible FROM reviews WHERE id = ?",
                              (review_id,)).fetchone()
    assert tuple(stored) == (comment, source, 1)
    teacher = client.get(f"/api/teachers/{seeded_teacher}").json()
    assert teacher["review_count"] == 1
    assert teacher["avg_teaching_quality"] == 4
    assert teacher["avg_test_difficulty"] == 3


def test_new_sensitive_review_is_accepted_and_author_notice_is_segmented(client, seeded_teacher):
    comment = "😀 The class was fucking hard, but explanations helped."
    response = client.post(f"/api/teachers/{seeded_teacher}/reviews", json={
        "teaching_quality": 4, "test_difficulty": 3,
        "homework_load": 2, "easygoingness": 5,
        "would_take_again": True, "comment": comment,
    })
    assert response.status_code == 200
    review_id = response.json()["id"]
    detail = client.get(f"/api/teachers/{seeded_teacher}").json()
    mine = detail["my_recent_review"]
    assert mine["id"] == review_id
    assert mine["comment"] == comment
    assert [p["text"] for p in mine["comment_segments"] if p["sensitive"]] == ["fucking"]
    assert mine["revoke_window_seconds"] == 60
    assert detail["review_count"] == 1
    assert detail["wta_percent"] == 100
    public = client.get(f"/api/teachers/{seeded_teacher}/reviews").json()["reviews"]
    assert [r["id"] for r in public] == [review_id]


def test_admin_moderation_keeps_original_text_and_visibility(client, seeded_teacher):
    comment = "Those fucking tests were difficult."
    review_id = insert_review(seeded_teacher, comment)
    response = client.get("/api/admin/reviews", params={"teacher_id": seeded_teacher},
                          headers={"Authorization": "Bearer test-admin-token"})
    assert response.status_code == 200
    review = response.json()["reviews"][0]
    assert review["id"] == review_id
    assert review["comment"] == comment
    assert review["is_visible"] is True
    assert "comment_segments" not in review
    assert client.get("/api/admin/reviews").status_code == 401


def test_filter_does_not_change_vote_order_pagination_or_hidden_state(client, seeded_teacher):
    clean_id = insert_review(seeded_teacher, "Clear notes and strict marking.")
    masked_id = insert_review(seeded_teacher, "Hard as shit, but clear explanations.")
    insert_review(seeded_teacher, "Previously hidden review with shit.", visible=0)
    with db.get_conn() as conn:
        conn.execute("INSERT INTO review_votes (review_id, ip_hash, vote) VALUES (?, ?, 1)",
                     (masked_id, "mask-test-voter"))
    first = client.get(f"/api/teachers/{seeded_teacher}/reviews", params={"limit": 1}).json()
    assert first["has_more"] is True
    assert first["reviews"][0]["id"] == masked_id
    assert first["reviews"][0]["likes"] == 1
    second = client.get(f"/api/teachers/{seeded_teacher}/reviews",
                        params={"limit": 2, "offset": 1}).json()
    assert second["has_more"] is False
    assert [r["id"] for r in second["reviews"]] == [clean_id]
    assert second["reviews"][0]["comment_segments"] == [
        {"text": "Clear notes and strict marking.", "sensitive": False}
    ]
    assert client.get(f"/api/teachers/{seeded_teacher}").json()["review_count"] == 2


def test_rating_only_review_retains_null_comment(client, seeded_teacher):
    insert_review(seeded_teacher, None)
    review = client.get(f"/api/teachers/{seeded_teacher}/reviews").json()["reviews"][0]
    assert review["comment"] is None
    assert review["comment_segments"] == []
