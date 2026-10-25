import re
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    issue_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS issues (
    issuecode TEXT PRIMARY KEY,
    pubcode TEXT NOT NULL,
    number TEXT NOT NULL,
    title TEXT,
    date TEXT,
    sort_num INTEGER NOT NULL DEFAULT 0,
    sort_rest TEXT NOT NULL DEFAULT '',
    cover_site TEXT,
    cover_url TEXT
);
CREATE INDEX IF NOT EXISTS issues_pub ON issues(pubcode, sort_num, sort_rest);
-- Le letture non vengono mai toccate dall'importazione dei dati Inducks.
CREATE TABLE IF NOT EXISTS reads (
    issuecode TEXT PRIMARY KEY,
    read_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS followed (
    pubcode TEXT PRIMARY KEY,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with session() as conn:
        conn.executescript(SCHEMA)
        first_run = conn.execute("SELECT value FROM meta WHERE key='initialized'").fetchone() is None
        if first_run:
            conn.executemany("INSERT OR IGNORE INTO followed(pubcode) VALUES (?)", [(c,) for c in config.DEFAULT_FOLLOWED])
            conn.execute("INSERT INTO meta(key, value) VALUES ('initialized', '1')")


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


_num_re = re.compile(r"^\s*(\d+)(.*)$")


def sort_key(number: str):
    """Ordina i numeri in modo naturale: '2', '10', '100A', 'Speciale'."""
    m = _num_re.match(number or "")
    if m:
        return int(m.group(1)), m.group(2).strip().lower()
    return 10**9, (number or "").lower()
