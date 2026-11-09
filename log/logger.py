import logging
import os
import sys
import threading
import time

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PLUGIN_DIR, "logs")

# 启动时立即尝试创建目录；失败打 stderr，不再静默
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
    _LOG_DIR_OK = True
except Exception as _e:
    print(
        f"[her_monitor_action_master] 无法创建日志目录 {_LOG_DIR}: {_e}，"
        f"将使用 stderr fallback",
        file=sys.stderr,
    )
    _LOG_DIR_OK = False

_logger = logging.getLogger("her_monitor_action_master")
_logger.setLevel(logging.INFO)
_logger.propagate = False

_handlers = {}
_lock = threading.Lock()

# ============================================================================
# 启动错误日志：每次启动清空，只写 register() 期间的错误
# 文件名：logs/startup_error.<role>.log
# 不受 config.logging 控制
# ============================================================================
_startup_role = None
_startup_lock = threading.Lock()


def set_startup_role(role):
    """设置当前进程角色（dashboard/gateway/cli），决定启动错误日志文件名。"""
    global _startup_role
    _startup_role = role or "unknown"


def _get_startup_log_path():
    role = _startup_role or "unknown"
    return os.path.join(_LOG_DIR, f"startup_error.{role}.log")


def clear_startup_log():
    """清空当前角色的启动错误日志。模块加载时调用一次。"""
    if not _LOG_DIR_OK:
        return
    with _startup_lock:
        try:
            p = _get_startup_log_path()
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def log_startup_error(msg, agent=None):
    """写启动错误日志。不受 config.logging 控制。

    - append 到 logs/startup_error.<role>.log
    - 同时打 stderr（Hermes 启动收集器会捕获）
    - 同时走 log_error（穿透 config，进 logs/<agent>.log）
    """
    text = str(msg)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    role = _startup_role or "unknown"

    if _LOG_DIR_OK:
        with _startup_lock:
            try:
                os.makedirs(_LOG_DIR, exist_ok=True)
                p = _get_startup_log_path()
                with open(p, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] [{role}] {text}\n")
            except Exception:
                pass

    try:
        print(f"[her_monitor_action_master] 启动错误({role}): {text}",
              file=sys.stderr, flush=True)
    except Exception:
        pass

    try:
        log_error(text, agent=agent or "_startup")
    except Exception:
        pass


def _is_enabled(force=False):
    if force:
        return True
    try:
        from config import get_config
        return get_config().is_logging_enabled()
    except Exception as e:
        # config 加载失败时**默认开启**，宁可多写不能静默关闭
        print(
            f"[her_monitor_action_master] config 加载失败，日志默认开启: {e}",
            file=sys.stderr,
        )
        return True


def _handler_for(agent):
    key = agent or "_global"
    with _lock:
        h = _handlers.get(key)
        if h is not None:
            return h

        if not _LOG_DIR_OK:
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(logging.Formatter(
                "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            _handlers[key] = h
            return h

        path = os.path.join(_LOG_DIR, f"{key}.log")
        try:
            h = logging.FileHandler(path, encoding="utf-8")
            h.setFormatter(logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            _handlers[key] = h
            return h
        except Exception as e:
            print(
                f"[her_monitor_action_master] 无法创建日志文件 {path}: {e}，"
                f"改用 stderr fallback",
                file=sys.stderr,
            )
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(logging.Formatter(
                "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            _handlers[key] = h
            return h


def log(msg, agent=None, level=logging.INFO, force=False):
    if not _is_enabled(force=force):
        return
    try:
        record = _logger.makeRecord(
            _logger.name, level, __file__, 0, str(msg), (), None
        )
        _handler_for(agent).emit(record)
    except Exception as e:
        try:
            print(
                f"[her_monitor_action_master] 日志写入失败: {e}: {msg}",
                file=sys.stderr,
            )
        except Exception:
            pass


def log_error(msg, agent=None):
    log(msg, agent=agent, level=logging.ERROR, force=True)


def log_warning(msg, agent=None):
    log(msg, agent=agent, level=logging.WARNING)