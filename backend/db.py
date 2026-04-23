import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get("BIPH_DB_PATH", str(Path(__file__).parent / "biph.db"))
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text())
    # Idempotent column additions for DBs that predate schema changes.
    # ALTER TABLE ADD COLUMN is the SQLite-safe way to migrate in place; we
    # swallow the duplicate-column error so repeat boots are no-ops.
    for table, column, ctype in (
        ("teachers", "courses", "TEXT"),
        ("teacher_submissions", "courses", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ctype}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    conn.commit()
    conn.close()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
