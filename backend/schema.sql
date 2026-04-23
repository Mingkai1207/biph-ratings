CREATE TABLE IF NOT EXISTS teachers (
  id             TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  subject        TEXT,
  courses        TEXT,
  legacy_id      TEXT UNIQUE,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  is_visible     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS reviews (
  id                 TEXT PRIMARY KEY,
  teacher_id         TEXT NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
  teaching_quality   INTEGER NOT NULL CHECK (teaching_quality BETWEEN 1 AND 5),
  test_difficulty    INTEGER NOT NULL CHECK (test_difficulty  BETWEEN 1 AND 5),
  homework_load      INTEGER NOT NULL CHECK (homework_load    BETWEEN 1 AND 5),
  easygoingness      INTEGER NOT NULL CHECK (easygoingness    BETWEEN 1 AND 5),
  comment            TEXT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  ip_hash            TEXT,
  source             TEXT NOT NULL DEFAULT 'user',
  legacy_id          TEXT UNIQUE,
  is_visible         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS teacher_submissions (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  subject     TEXT,
  courses     TEXT,
  ip_hash     TEXT,
  status      TEXT NOT NULL DEFAULT 'pending',
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS suggestions (
  id           TEXT PRIMARY KEY,
  body         TEXT NOT NULL,
  ip_hash      TEXT,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  is_resolved  INTEGER NOT NULL DEFAULT 0,
  resolved_at  TEXT
);

-- One thumbs-up / thumbs-down per IP per review. Primary key on
-- (review_id, ip_hash) makes double-voting a no-op at the DB level.
-- Switching sides is handled by INSERT ... ON CONFLICT DO UPDATE in the
-- vote endpoint, and "clear my vote" is a DELETE on the same key.
CREATE TABLE IF NOT EXISTS review_votes (
  review_id   TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
  ip_hash     TEXT NOT NULL,
  vote        INTEGER NOT NULL CHECK (vote IN (-1, 1)),
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (review_id, ip_hash)
);

CREATE INDEX IF NOT EXISTS idx_reviews_teacher_created ON reviews(teacher_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_teachers_name ON teachers(name);
CREATE INDEX IF NOT EXISTS idx_teachers_subject ON teachers(subject);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON teacher_submissions(status);
CREATE INDEX IF NOT EXISTS idx_suggestions_resolved_created ON suggestions(is_resolved, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_votes_review ON review_votes(review_id);
