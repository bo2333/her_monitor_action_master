import json
import os
import sys
import threading
import time

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_FILE = os.path.join(_PLUGIN_DIR, "config", "master_config.json")
_DEF_CONFIG_FILE = os.path.join(_PLUGIN_DIR, "config", "master_config.def.json")

_TTL = 1.0

# 缓存从 .def.json 读到的默认结构，避免每次 _ensure_complete 都读盘
_default_lock = threading.Lock()
_default_cache = None


def _load_default_config():
    """从 .def.json 加载默认配置结构。这是唯一的默认配置源。

    - 成功：返回 dict
    - 失败（文件缺失/损坏）：返回空 dict，写 stderr，不抛异常（让插件降级运行）
    """
    global _default_cache
    with _default_lock:
        if _default_cache is not None:
            return json.loads(json.dumps(_default_cache))

    try:
        with open(_DEF_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("顶层不是 JSON 对象")
    except Exception as e:
        print(
            f"[her_monitor_action_master] 无法加载默认配置 "
            f"{_DEF_CONFIG_FILE}: {e!r}",
            file=sys.stderr,
        )
        data = {}

    with _default_lock:
        _default_cache = json.loads(json.dumps(data))
    return data


def invalidate_default_cache():
    """配置模板被外部修改后调此函数，下次 _load_default_config 重新读盘。"""
    global _default_cache
    with _default_lock:
        _default_cache = None


class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self._config = _load_default_config()
        self._mtime = 0.0
        self._enabled_cache = None
        self._enabled_cached_at = 0.0
        self._logging_cache = None
        self._logging_cached_at = 0.0
        self._ensure_file()
        self._load_if_changed()

    def _ensure_file(self):
        """确保 master_config.json 存在。

        唯一来源：master_config.def.json。缺失则写 stderr，不生成。
        """
        if os.path.exists(_CONFIG_FILE):
            return

        try:
            os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
        except Exception as e:
            print(
                f"[her_monitor_action_master] 创建配置目录失败: {e!r}",
                file=sys.stderr,
            )
            return

        try:
            with open(_DEF_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(
                f"[her_monitor_action_master] 无法从 {_DEF_CONFIG_FILE} "
                f"生成配置: {e!r}",
                file=sys.stderr,
            )
            return

        try:
            tmp = _CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _CONFIG_FILE)
            print(
                f"[her_monitor_action_master] 已从 {_DEF_CONFIG_FILE} "
                f"生成默认配置 {_CONFIG_FILE}",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"[her_monitor_action_master] 写入 {_CONFIG_FILE} 失败: {e!r}",
                file=sys.stderr,
            )

    def _ensure_complete(self, data):
        """把 data 补全为与 .def.json 一致的结构。

        返回 (cfg, changed)：
        - cfg 是补全后的完整配置
        - changed 表示 data 相比 cfg 有缺失字段（需要写回）
        用户自己加的额外字段会被保留。
        """
        default_cfg = _load_default_config()

        if not isinstance(default_cfg, dict) or not default_cfg:
            # .def.json 不可用，无法补全；原样返回
            if isinstance(data, dict):
                return data, False
            return {}, True

        cfg = json.loads(json.dumps(default_cfg))
        changed = False

        if not isinstance(data, dict):
            return cfg, True

        for k, default_val in default_cfg.items():
            if k not in data:
                changed = True
                continue

            if isinstance(default_val, dict) and isinstance(data[k], dict):
                merged = json.loads(json.dumps(default_val))
                for sk in default_val:
                    if sk in data[k]:
                        merged[sk] = data[k][sk]
                    else:
                        changed = True
                for sk in data[k]:
                    if sk not in merged:
                        merged[sk] = data[k][sk]
                cfg[k] = merged
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
                f"[her_monitor_action_master] 写回 master_config.json 失败: {e!r}",
                file=sys.stderr,
            )
            return False

    def _load_if_changed(self):
        try:
            m = os.path.getmtime(_CONFIG_FILE)
        except Exception:
            # 文件被外部删除 → 尝试重新生成
            self._ensure_file()
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
                f"[her_monitor_action_master] master_config.json 解析失败: {e!r}",
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
                    "[her_monitor_action_master] master_config.json "
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