import json
import os
import time

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATUS_DIR = os.path.join(_PLUGIN_DIR, "status")


def _atomic_write(path, data):
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_runtime(agent, deps_report, db_root, version="1.2.1"):
    """两个文件：
    - status/{agent}.json —— 按 Agent 分文件，避免多进程互相覆盖
    - status/runtime.json —— 兼容旧 booth 读法（最后一次写者为胜）
    """
    data = {
        "pid": os.getpid(),
        "agent": agent or "unknown",
        "started_at": int(time.time()),
        "deps": deps_report,
        "db_root": db_root,
        "plugin_dir": _PLUGIN_DIR,
        "version": version,
    }
    try:
        os.makedirs(_STATUS_DIR, exist_ok=True)
        _atomic_write(os.path.join(_STATUS_DIR, f"{agent or 'unknown'}.json"), data)
    except Exception:
        pass
    try:
        _atomic_write(os.path.join(_STATUS_DIR, "runtime.json"), data)
    except Exception:
        pass