import os
import sqlite3
import threading

_SCHEMA_CACHE = None
_CONNECTIONS = {}
_LOCK = threading.Lock()


def _load_schema():
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    with open(path, "r", encoding="utf-8") as f:
        _SCHEMA_CACHE = f.read()
    return _SCHEMA_CACHE


def get_connection(db_path):
    with _LOCK:
        if db_path in _CONNECTIONS:
            return _CONNECTIONS[db_path]
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript(_load_schema())
        _CONNECTIONS[db_path] = conn
        return conn


def ensure_db(db_path):
    get_connection(db_path)
    return db_path