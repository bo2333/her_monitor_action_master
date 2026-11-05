import json
import os
import threading

from .defaults import DEFAULT_CONFIG

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_FILE = os.path.join(_PLUGIN_DIR, "config", "master_config.json")


class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self._config = json.loads(json.dumps(DEFAULT_CONFIG))
        self._ensure_file()
        self._load()

    def _ensure_file(self):
        if os.path.exists(_CONFIG_FILE):
            return
        try:
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load(self):
        with self._lock:
            if not os.path.exists(_CONFIG_FILE):
                return
            try:
                with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k in ("enabled", "db_root"):
                        if k in data:
                            self._config[k] = data[k]
                    if "remote" in data and isinstance(data["remote"], dict):
                        self._config["remote"].update(data["remote"])
            except Exception:
                pass

    def is_enabled(self):
        with self._lock:
            return bool(self._config.get("enabled", False))

    def get_db_root(self):
        with self._lock:
            return self._config.get("db_root", DEFAULT_CONFIG["db_root"])

    def get_remote(self):
        with self._lock:
            return json.loads(json.dumps(self._config.get("remote", {})))

    def reload(self):
        self._load()


_instance = Config()


def get_config():
    return _instance