import os
import sqlite3
from contextlib import contextmanager
from .config_helper import read_config


def _strip_quotes(p: str) -> str:
    if not isinstance(p, str):
        return p
    return p.strip().strip('"').strip("'").strip('“”').strip('‘’')


def _get_llm_db_path() -> str:
    conf = read_config() or {}
    path = conf.get('llm_db_path') or conf.get('db_path') or 'llm_app.db'
    path = _strip_quotes(path)
    if not os.path.isabs(path):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.abspath(os.path.join(base, path))
    return path


SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS events (
    id INTEGER NOT NULL,
    time TEXT NOT NULL,
    command TEXT NOT NULL,
    parameter TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(time);
'''


def _open_conn(db_path: str):
    conn = sqlite3.connect(db_path, timeout=1.0, isolation_level=None)
    try:
        cur = conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL;')
        cur.execute('PRAGMA synchronous=NORMAL;')
        cur.execute('PRAGMA busy_timeout=1000;')
    except Exception:
        pass
    return conn


def init_llm_db():
    db_path = _get_llm_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with _open_conn(db_path) as conn:
        conn.executescript(SCHEMA_SQL)


@contextmanager
def _conn():
    db_path = _get_llm_db_path()
    conn = _open_conn(db_path)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def clear_llm_events():
    with _conn() as conn:
        conn.executescript(SCHEMA_SQL)
        cur = conn.cursor()
        try:
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('DELETE FROM events')
            cur.execute('COMMIT')
        except Exception:
            try:
                cur.execute('ROLLBACK')
            except Exception:
                pass


def overwrite_llm_first_event(ev_id: int, ev_time: str, command: str, parameter: str):
    with _conn() as conn:
        conn.executescript(SCHEMA_SQL)
        cur = conn.cursor()
        try:
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('DELETE FROM events')
            cur.execute(
                'INSERT INTO events(id, time, command, parameter) VALUES (?, ?, ?, ?)',
                (ev_id, ev_time, command, parameter)
            )
            cur.execute('COMMIT')
        except Exception:
            try:
                cur.execute('ROLLBACK')
            except Exception:
                pass
