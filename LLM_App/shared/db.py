import os
import sqlite3
from contextlib import contextmanager
from .config_helper import read_config

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _strip_quotes(p: str) -> str:
    if not isinstance(p, str):
        return p
    return p.strip().strip('"').strip("'").strip('“”').strip('‘’')


def _get_db_path():
    conf = read_config() or {}
    path = conf.get('db_path') or 'llm_app.db'
    path = _strip_quotes(path)
    if not os.path.isabs(path):
        path = os.path.abspath(os.path.join(APP_DIR, path))
    return path

# 保留旧常量以兼容历史引用，但不再直接用于连接
DB_PATH = _get_db_path()

SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    ref_id INTEGER,
    payload TEXT,
    result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
'''


def init_db():
    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


@contextmanager
def get_conn():
    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
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
