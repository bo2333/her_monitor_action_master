import json
import os
import time

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATUS_DIR = os.path.join(_PLUGIN_DIR, "status")

_MAX_AGE_SEC = 24 * 3600


def _cleanup_old_files():
    """删除超过 24 小时的进程状态文件，防止无界累积。"""
    try:
        now = time.time()
        for fname in os.listdir(_STATUS_DIR):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(_STATUS_DIR, fname)
            try:
                if now - os.path.getmtime(path) > _MAX_AGE_SEC:
                    os.remove(path)
            except Exception:
                pass
    except Exception:
        pass


def write_runtime(agent, deps_report, db_root, version="1.2.11", role="unknown"):
    data = {
        "pid": os.getpid(),
        "agent": agent or "unknown",
        "role": role,
        "started_at": int(time.time()),
        "deps": deps_report,
        "db_root": db_root,
        "plugin_dir": _PLUGIN_DIR,
        "version": version,
    }
    try:
        os.makedirs(_STATUS_DIR, exist_ok=True)
        _cleanup_old_files()
        path = os.path.join(
            _STATUS_DIR,
            f"{agent or 'unknown'}.{role}.{os.getpid()}.json",
        )
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass