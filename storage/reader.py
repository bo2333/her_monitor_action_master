import os
import sqlite3
import time

from log import log


def load_recent(db_path, limit=500):
    """读最近 limit 条事件，返回 wire format dict 列表（时间正序）。"""
    if not db_path or not os.path.exists(db_path):
        return []

    agent = None
    if db_path.endswith(".db"):
        agent = os.path.basename(db_path)[:-3]

    rows = []
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    except Exception as e:
        log(f"[reader] 读取失败 {db_path}: {e!r}", agent=agent)
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    result = []
    for r in reversed(rows):
        result.append({
            "ts": int(r["ts"] or time.time()),
            "user": str(r["user"] or "unknown"),
            "flow": int(r["flow"] or 0),
            "conn": str(r["conn"] or ""),
            "action": str(r["action"] or ""),
            "level": str(r["level"] or ""),
            "input_tokens": int(r["input_tokens"] or 0),
            "output_tokens": int(r["output_tokens"] or 0),
            "total_tokens": int(r["total_tokens"] or 0),
            "cost": float(r["cost"] or 0.0),
        })
    return result