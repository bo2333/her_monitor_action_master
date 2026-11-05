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
        self._mtime = 0.0
        self._ensure_file()
        self._load_if_changed()

    def _ensure_file(self):
        if os.path.exists(_CONFIG_FILE):
            return
        try:
            os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_if_changed(self):
        try:
            m = os.path.getmtime(_CONFIG_FILE)
        except Exception:
            return
        if m == self._mtime:
            return
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = json.loads(json.dumps(DEFAULT_CONFIG))
            if isinstance(data, dict):
                for k in ("enabled", "db_root"):
                    if k in data:
                        cfg[k] = data[k]
                if "remote" in data and isinstance(data["remote"], dict):
                    cfg["remote"].update(data["remote"])
            with self._lock:
                self._config = cfg
                self._mtime = m
        except Exception:
            pass

    def reload(self):
        self._mtime = 0.0
        self._load_if_changed()

    def snapshot(self):
        self._load_if_changed()
        with self._lock:
            return json.loads(json.dumps(self._config))

    def is_enabled(self):
        self._load_if_changed()
        with self._lock:
            return bool(self._config.get("enabled", False))

    def get_db_root(self):
        self._load_if_changed()
        with self._lock:
            raw = self._config.get("db_root", "")
            if raw:
                return raw
            return os.path.join(_PLUGIN_DIR, "data")

    def get_remote(self):
        self._load_if_changed()
        with self._lock:
            return json.loads(json.dumps(self._config.get("remote", {})))


_instance = Config()


def get_config():
    return _instance