import json
import os
import sys
import threading
import time

from .defaults import DEFAULT_CONFIG

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_FILE = os.path.join(_PLUGIN_DIR, "config", "master_config.json")

_TTL = 1.0


class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self._config = json.loads(json.dumps(DEFAULT_CONFIG))
        self._mtime = 0.0
        self._enabled_cache = None
        self._enabled_cached_at = 0.0
        self._logging_cache = None
        self._logging_cached_at = 0.0
        self._ensure_file()
        self._load_if_changed()

    def _ensure_file(self):
        if os.path.exists(_CONFIG_FILE):
            return
        try:
            os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(
                f"[monitor_action_master] 创建默认配置失败: {e}",
                file=sys.stderr,
            )

    def _ensure_complete(self, data):
        """把 data 补全为和 DEFAULT_CONFIG 一致的结构。

        返回 (cfg, changed)：
        - cfg 是补全后的完整配置
        - changed 表示 data 相比 cfg 有缺失字段（需要写回）
        用户自己加的额外字段会被保留。
        """
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        changed = False

        if not isinstance(data, dict):
            return cfg, True

        for k, default_val in DEFAULT_CONFIG.items():
            if k not in data:
                changed = True
                continue

            if k == "remote" and isinstance(default_val, dict) \
                    and isinstance(data[k], dict):
                remote_cfg = json.loads(json.dumps(default_val))
                for rk in default_val:
                    if rk in data[k]:
                        remote_cfg[rk] = data[k][rk]
                    else:
                        changed = True
                for rk in data[k]:
                    if rk not in remote_cfg:
                        remote_cfg[rk] = data[k][rk]
                cfg["remote"] = remote_cfg
            else:
                cfg[k] = data[k]

        for k in data:
            if k not in cfg:
                cfg[k] = data[k]

        return cfg, changed

    def _save(self, cfg):
        try:
            tmp = _CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _CONFIG_FILE)
            return True
        except Exception as e:
            print(
                f"[monitor_action_master] 写回 master_config.json 失败: {e}",
                file=sys.stderr,
            )
            return False

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
        except Exception as e:
            print(
                f"[monitor_action_master] master_config.json 解析失败: {e}",
                file=sys.stderr,
            )
            return

        cfg, changed = self._ensure_complete(data)

        if changed:
            if self._save(cfg):
                try:
                    m = os.path.getmtime(_CONFIG_FILE)
                except Exception:
                    pass
                print(
                    "[monitor_action_master] master_config.json "
                    "已补全缺失字段并写回",
                    file=sys.stderr,
                )

        with self._lock:
            self._config = cfg
            self._mtime = m
            self._enabled_cache = None
            self._logging_cache = None

    def reload(self):
        self._mtime = 0.0
        with self._lock:
            self._enabled_cache = None
            self._logging_cache = None
        self._load_if_changed()

    def snapshot(self):
        self._load_if_changed()
        with self._lock:
            return json.loads(json.dumps(self._config))

    def is_enabled(self):
        now = time.time()
        with self._lock:
            if (self._enabled_cache is not None
                    and now - self._enabled_cached_at < _TTL):
                return self._enabled_cache
        self._load_if_changed()
        with self._lock:
            self._enabled_cache = bool(self._config.get("enabled", False))
            self._enabled_cached_at = now
            return self._enabled_cache

    def is_logging_enabled(self):
        """日志开关。MONITOR_LOG 环境变量优先级最高。"""
        env = os.environ.get("MONITOR_LOG")
        if env is not None:
            v = env.strip().lower()
            return v not in ("0", "false", "off", "no", "")
        now = time.time()
        with self._lock:
            if (self._logging_cache is not None
                    and now - self._logging_cached_at < _TTL):
                return self._logging_cache
        self._load_if_changed()
        with self._lock:
            self._logging_cache = bool(self._config.get("logging", False))
            self._logging_cached_at = now
            return self._logging_cache

    def get_db_root(self):
        self._load_if_changed()
        with self._lock:
            raw = (self._config.get("db_root") or "").strip()
            if raw:
                return raw
            return os.path.join(_PLUGIN_DIR, "data")

    def get_remote(self):
        self._load_if_changed()
        with self._lock:
            r = json.loads(json.dumps(self._config.get("remote", {})))
            r["host"] = str(r.get("host") or "127.0.0.1").strip()
            return r


_instance = Config()


def get_config():
    return _instance