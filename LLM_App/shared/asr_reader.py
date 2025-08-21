import os
import sqlite3
from contextlib import contextmanager
from .config_helper import read_config


def _strip_quotes(p: str) -> str:
    if not isinstance(p, str):
        return p
    return p.strip().strip('"').strip("'").strip('“”').strip('‘’')


def _get_asr_db_path() -> str:
    conf = read_config() or {}
    path = conf.get('asr_db_path') or conf.get('db_path') or 'asr_app.db'
    path = _strip_quotes(path)
    if not os.path.isabs(path):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.abspath(os.path.join(base, path))
    return path


@contextmanager
def _conn():
    db_path = _get_asr_db_path()
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def read_latest_event():
    """返回 (time_str, parameter_str) 或 None。如果表不存在或无数据返回 None。"""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT time, parameter FROM events ORDER BY id LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return row[0], row[1]
    except Exception:
        return None
