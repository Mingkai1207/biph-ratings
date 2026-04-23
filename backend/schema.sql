CREATE TABLE IF NOT EXISTS teachers (
  id             TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  subject        TEXT,
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
  ip_hash     TEXT,
  status      TEXT NOT NULL DEFAULT 'pending',
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_reviews_teacher_created ON reviews(teacher_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_teachers_name ON teachers(name);
CREATE INDEX IF NOT EXISTS idx_teachers_subject ON teachers(subject);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON teacher_submissions(status);
