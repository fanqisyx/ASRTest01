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


def init_db():
    # 每次根据当前配置动态解析 DB 路径
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


@contextmanager
def get_conn():
    # 每次根据当前配置动态解析 DB 路径
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def insert_event(ev_id: int, ev_time: str, command: str, parameter_json: str) -> None:
    """插入一条事件记录。id 由应用内自增维护。"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO events(id, time, command, parameter) VALUES (?, ?, ?, ?)',
            (ev_id, ev_time, command, parameter_json)
        )
        conn.commit()


def overwrite_first_event(ev_time: str, command: str, parameter_json: str) -> None:
    """覆盖数据库中的第一条记录（固定 id=1），保证表中最多只有一条信息。
    若不存在则创建，存在则替换。
    """
    with get_conn() as conn:
        cur = conn.cursor()
        # 保证最多一条：先清空表，再写入一条固定 id=1 的记录
        cur.execute('DELETE FROM events')
        cur.execute(
            'INSERT INTO events(id, time, command, parameter) VALUES (1, ?, ?, ?)',
            (ev_time, command, parameter_json)
        )
        conn.commit()


def clear_events() -> None:
    """清空 events 表（启动时调用，等价于清除第一行）。"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute('DELETE FROM events')
        conn.commit()
