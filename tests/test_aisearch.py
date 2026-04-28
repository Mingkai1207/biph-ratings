"""
Tests for the AI smart-search endpoint. We mock Groq via monkeypatch so
tests stay deterministic, never hit the network, and exercise the full
parse → validate → SQL flow.
"""
import json
import uuid

import pytest

from backend import aisearch, db


# ——— Validator unit tests (no network involved)

def test_validate_parsed_coerces_invalid_intent_to_rank():
    out = aisearch.validate_parsed({"intent": "nonsense"})
    assert out["intent"] == "rank"


def test_validate_parsed_drops_unknown_sort_field():
    out = aisearch.validate_parsed({"sort_by": "DROP TABLE teachers"})
    assert out["sort_by"] is None


def test_validate_parsed_clamps_limit():
    assert aisearch.validate_parsed({"limit": 9999})["limit"] == 20
    assert aisearch.validate_parsed({"limit": -5})["limit"] == 1


def test_validate_parsed_defaults_min_reviews_to_5():
    assert aisearch.validate_parsed({})["min_reviews"] == 5


def test_validate_parsed_clamps_min_reviews_upper_bound():
    assert aisearch.validate_parsed({"min_reviews": 999})["min_reviews"] == 50


def test_validate_parsed_rejects_non_dict():
    with pytest.raises(ValueError):
        aisearch.validate_parsed("not a dict")


# ——— Endpoint tests with mocked Groq

@pytest.fixture
def seeded_ranking_teachers():
    """Three teachers with known averages so we can verify ranking order."""
    ids = []
    with db.get_conn() as conn:
        for name, subject, ratings in [
            ("HighRated Teacher",   "Math",    [(5, 5, 5, 5)] * 6),  # avg 5.00
            ("MiddleRated Teacher", "Math",    [(3, 3, 3, 3)] * 6),  # avg 3.00
            ("LowRated Teacher",    "Math",    [(1, 1, 1, 1)] * 6),  # avg 1.00
        ]:
            tid = uuid.uuid4().hex
            ids.append(tid)
            conn.execute(
                "INSERT INTO teachers (id, name, subject, is_visible) VALUES (?, ?, ?, 1)",
                (tid, name, subject),
            )
            for tq, td, hl, eg in ratings:
                conn.execute(
                    "INSERT INTO reviews (id, teacher_id, teaching_quality, "
                    "test_difficulty, homework_load, easygoingness, is_visible) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (uuid.uuid4().hex, tid, tq, td, hl, eg),
                )
    return ids


def test_search_ranks_descending_when_groq_returns_rank_intent(client, seeded_ranking_teachers, monkeypatch):
    """User asks 'best math teacher' → Groq returns rank intent → DB returns
    teachers sorted by rating desc. The high-rated teacher must come first."""
    monkeypatch.setattr(aisearch, "call_llm", lambda q: {
        "intent": "rank",
        "sort_by": "avg_rating",
        "order": "desc",
        "subject_filter": "Math",
        "min_reviews": 1,
        "limit": 10,
        "explanation_en": "Top-rated Math teachers.",
        "explanation_zh": "评分最高的数学老师。",
    })
    r = client.post("/api/search", json={"query": "best math teacher"})
    assert r.status_code == 200
    data = r.json()
    assert data["fallback"] is False
    names = [t["name"] for t in data["teachers"]]
    assert names[0] == "HighRated Teacher"
    assert names[-1] == "LowRated Teacher"
    assert "Top-rated" in data["explanation_en"]


def test_search_ranks_ascending_when_groq_returns_asc(client, seeded_ranking_teachers, monkeypatch):
    """'teacher with the most bad comments' → asc order → low-rated first."""
    monkeypatch.setattr(aisearch, "call_llm", lambda q: {
        "intent": "rank",
        "sort_by": "avg_rating",
        "order": "asc",
        "subject_filter": None,
        "min_reviews": 1,
        "limit": 5,
        "explanation_en": "Lowest-rated teachers.",
        "explanation_zh": "评分最低的老师。",
    })
    r = client.post("/api/search", json={"query": "worst teacher"})
    data = r.json()
    names = [t["name"] for t in data["teachers"] if t["name"].endswith(" Teacher")]
    # First of our three test teachers (by rating asc) must be the low one
    assert names[0] == "LowRated Teacher"


def test_search_falls_back_to_keyword_when_groq_fails(client, seeded_ranking_teachers, monkeypatch):
    """Groq raises (timeout, auth, parse error) → /api/search must return
    teachers from a keyword search rather than 500-ing."""
    def boom(q):
        raise RuntimeError("Groq unreachable")
    monkeypatch.setattr(aisearch, "call_llm", boom)

    r = client.post("/api/search", json={"query": "HighRated"})
    assert r.status_code == 200
    data = r.json()
    assert data["fallback"] is True
    names = [t["name"] for t in data["teachers"]]
    assert "HighRated Teacher" in names


def test_search_rejects_too_short_query(client):
    r = client.post("/api/search", json={"query": "x"})
    assert r.status_code == 422  # pydantic validation


def test_search_rate_limit_returns_429(client, monkeypatch):
    """20 successful queries exhaust the per-IP daily budget; the 21st 429s.
    TestClient always uses 127.0.0.1, so prior tests in the file have already
    incremented the counter — wipe the log so this test is self-contained."""
    with db.get_conn() as conn:
        conn.execute("DELETE FROM ai_search_log")

    monkeypatch.setattr(aisearch, "call_llm", lambda q: {
        "intent": "rank",
        "sort_by": "avg_rating",
        "order": "desc",
        "subject_filter": None,
        "min_reviews": 1,
        "limit": 5,
        "explanation_en": "Top.",
        "explanation_zh": "Top.",
    })
    for _ in range(aisearch.MAX_AI_SEARCHES_PER_DAY):
        assert client.post("/api/search", json={"query": "anything"}).status_code == 200
    over = client.post("/api/search", json={"query": "anything"})
    assert over.status_code == 429
    assert over.json()["error"] == "rate_limited"


# ——— Provider selection (OpenAI vs Groq) ——————————————————————

def test_active_provider_prefers_openai_when_both_keys_set(monkeypatch):
    """OpenAI > Groq when both keys are present. Order matters because OpenAI
    typically gives better edge-query parsing than Llama 3.3 70B on Groq."""
    monkeypatch.setattr(aisearch, "OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setattr(aisearch, "GROQ_API_KEY", "gsk-test-groq")
    assert aisearch.active_provider() == "openai"


def test_active_provider_falls_back_to_groq_when_only_groq_set(monkeypatch):
    monkeypatch.setattr(aisearch, "OPENAI_API_KEY", "")
    monkeypatch.setattr(aisearch, "GROQ_API_KEY", "gsk-test-groq")
    assert aisearch.active_provider() == "groq"


def test_active_provider_returns_none_when_no_keys(monkeypatch):
    monkeypatch.setattr(aisearch, "OPENAI_API_KEY", "")
    monkeypatch.setattr(aisearch, "GROQ_API_KEY", "")
    assert aisearch.active_provider() is None


def test_call_llm_raises_when_no_provider(monkeypatch):
    """Without a key configured we don't silently call something — the caller
    needs to know so it can fall back to keyword search."""
    monkeypatch.setattr(aisearch, "OPENAI_API_KEY", "")
    monkeypatch.setattr(aisearch, "GROQ_API_KEY", "")
    with pytest.raises(RuntimeError, match="No LLM API key"):
        aisearch.call_llm("anything")
