import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.path.abspath(os.path.join(os.getcwd(), 'asr_bus.db'))

SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,           -- user|assistant|system|event
    content TEXT NOT NULL,
    meta TEXT,                    -- JSON string for extras
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,           -- asr|llm|tts
    status TEXT NOT NULL,         -- pending|processing|done|error
    ref_id INTEGER,               -- optional link to messages.id
    payload TEXT,                 -- JSON body
    result TEXT,                  -- JSON body
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
'''


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def insert_message(role: str, content: str, meta: str | None = None) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO messages(role, content, meta) VALUES (?, ?, ?)',
            (role, content, meta)
        )
        conn.commit()
        return cur.lastrowid


def create_task(kind: str, payload: str, ref_id: int | None = None, status: str = 'pending') -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO tasks(kind, status, ref_id, payload) VALUES (?, ?, ?, ?)',
            (kind, status, ref_id, payload)
        )
        conn.commit()
        return cur.lastrowid


def claim_next_task(kind: str) -> tuple[int, str] | None:
    """Atomically claim one pending task for a given kind."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute('BEGIN IMMEDIATE')
        cur.execute("SELECT id, payload FROM tasks WHERE kind=? AND status='pending' ORDER BY id LIMIT 1", (kind,))
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        task_id, payload = row
        cur.execute("UPDATE tasks SET status='processing', updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
        conn.commit()
        return task_id, payload


def finish_task(task_id: int, result: str, status: str = 'done'):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tasks SET status=?, result=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, result, task_id)
        )
        conn.commit()
