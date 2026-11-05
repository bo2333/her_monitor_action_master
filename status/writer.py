import json
import os
import time

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATUS_DIR = os.path.join(_PLUGIN_DIR, "status")
_RUNTIME_FILE = os.path.join(_STATUS_DIR, "runtime.json")


def write_runtime(agent, deps_report, db_root, version="1.2.0"):
    try:
        os.makedirs(_STATUS_DIR, exist_ok=True)
        data = {
            "pid": os.getpid(),
            "agent": agent,
            "started_at": int(time.time()),
            "deps": deps_report,
            "db_root": db_root,
            "plugin_dir": _PLUGIN_DIR,
            "version": version,
        }
        tmp = _RUNTIME_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _RUNTIME_FILE)
    except Exception:
        pass