import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
 password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('student','admin')), created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 template TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
 cpu REAL NOT NULL, memory_mb INTEGER NOT NULL, created_at REAL NOT NULL,
 last_active REAL NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS backups (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 created_at REAL NOT NULL, size INTEGER NOT NULL, storage TEXT NOT NULL, object_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, workspace_id TEXT,
 action TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS workspace_owner ON workspaces(owner_id);
CREATE INDEX IF NOT EXISTS session_expiry ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS login_time ON login_attempts(created_at);
"""


class Database:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def one(self, sql, args=()):
        with self.connect() as conn:
            row = conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql, args=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as conn:
            conn.execute(sql, args)
