import os
import sqlite3
from contextlib import contextmanager
from .config_helper import read_config

# 可配置的独立数据库文件，默认放在本应用目录
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_db_path():
    conf = read_config()
    path = conf.get('db_path')
    if not path:
        path = 'asr_app.db'
    # 相对路径则落在应用目录
    if not os.path.isabs(path):
        path = os.path.abspath(os.path.join(APP_DIR, path))
    return path


DB_PATH = _get_db_path()  # 兼容旧引用，不再直接使用该常量进行连接

# 新表结构：events(id, time, command, parameter)
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
    """打开连接并设置快速释放相关 PRAGMA，避免长时间文件锁。"""
    conn = sqlite3.connect(db_path, timeout=1.0, isolation_level=None)  # autocommit 模式
    try:
        cur = conn.cursor()
        # WAL 可减少写锁阻塞；busy_timeout 避免立即报错
        cur.execute('PRAGMA journal_mode=WAL;')
        cur.execute('PRAGMA synchronous=NORMAL;')
        cur.execute('PRAGMA busy_timeout=1000;')  # 1s 等待锁
    except Exception:
        pass
    return conn


def init_db():
    db_path = _get_db_path()
    with _open_conn(db_path) as conn:
        # autocommit 已启用，但仍显式执行脚本
        conn.executescript(SCHEMA_SQL)


@contextmanager
def get_conn():
    db_path = _get_db_path()
    conn = _open_conn(db_path)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def insert_event(ev_id: int, ev_time: str, command: str, parameter_json: str) -> None:
    """插入一条事件记录。id 由应用内自增维护。"""
    with get_conn() as conn:
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')  # 缩短写锁范围
            cur.execute(
                'INSERT INTO events(id, time, command, parameter) VALUES (?, ?, ?, ?)',
                (ev_id, ev_time, command, parameter_json)
            )
            cur.execute('COMMIT')
        except Exception:
            try:
                cur.execute('ROLLBACK')
            except Exception:
                pass


def overwrite_first_event(ev_time: str, command: str, parameter_json: str) -> None:
    """覆盖数据库中的第一条记录（固定 id=1），保证表中最多只有一条信息。
    若不存在则创建，存在则替换。
    """
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('DELETE FROM events')
            cur.execute(
                'INSERT INTO events(id, time, command, parameter) VALUES (1, ?, ?, ?)',
                (ev_time, command, parameter_json)
            )
            cur.execute('COMMIT')
        except Exception:
            try:
                cur.execute('ROLLBACK')
            except Exception:
                pass


def clear_events() -> None:
    """清空 events 表（启动时调用，等价于清除第一行）。"""
    with get_conn() as conn:
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
