"""Small SQLite store: chats, messages, approvals, routines."""

import sqlite3
import time
from contextlib import contextmanager

from . import config

DB_FILE = config.HOME / "orbit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'auto',
    claude_session TEXT,
    codex_session TEXT,
    last_provider TEXT,
    running INTEGER NOT NULL DEFAULT 0,
    routine_id INTEGER,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,          -- user | assistant | tool | system | error
    content TEXT NOT NULL,
    model TEXT,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    tool TEXT NOT NULL,
    detail TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | denied
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    cron TEXT NOT NULL,
    prompt TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'auto',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run REAL,
    created REAL NOT NULL
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_FILE, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        # A restart stops any running turn, so clear the flag.
        c.execute("UPDATE chats SET running = 0")


def q(sql: str, *args) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql: str, *args) -> dict | None:
    rows = q(sql, *args)
    return rows[0] if rows else None


def run(sql: str, *args) -> int:
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def add_message(chat_id: int, role: str, content: str, model: str | None = None) -> int:
    return run(
        "INSERT INTO messages (chat_id, role, content, model, created) VALUES (?,?,?,?,?)",
        chat_id, role, content, model, time.time(),
    )
