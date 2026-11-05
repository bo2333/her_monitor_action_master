import os
import sqlite3
import threading

_SCHEMA = None
_CONNS = {}
_LOCK = threading.Lock()


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
        with open(p, "r", encoding="utf-8") as f:
            _SCHEMA = f.read()
    return _SCHEMA


def get_connection(db_path):
    with _LOCK:
        if db_path in _CONNS:
            return _CONNS[db_path]
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript(_schema())
        conn.commit()
        _CONNS[db_path] = conn
        return conn


def invalidate_connection(db_path):
    with _LOCK:
        conn = _CONNS.pop(db_path, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def ensure_db(agent_name):
    from config import get_config
    root = get_config().get_db_root()
    p = os.path.join(root, f"{agent_name or 'unknown'}.db")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_schema())
        conn.commit()
    finally:
        conn.close()
    return p