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
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript(_schema())
        _CONNS[db_path] = conn
        return conn


def ensure_db(agent_name):
    from config import get_config
    root = get_config().get_db_root()
    p = os.path.join(root, f"{agent_name or 'unknown'}.db")
    get_connection(p)
    return p