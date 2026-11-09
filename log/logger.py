import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PLUGIN_DIR, "logs")

_MAX_LOG_BYTES = 256 * 1024 * 1024
_BACKUP_COUNT = 3

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
# 启动期状态
#   两个文件都在启动期写入，register() 结束后停写：
#   - _startup.log                启动流水账（每次启动清空内容，保留文件）
#   - startup_error.<role>.log    启动错误专档（每次启动清空内容，保留文件）
#   两个文件都不会被删除，只是内容在每次启动时被截断为 0。
# ============================================================================
_startup_phase = True
_startup_lock = threading.Lock()
_startup_role = "unknown"

_STARTUP_LOG_FILE = os.path.join(_LOG_DIR, "_startup.log")


def _startup_error_file():
    role = _startup_role or "unknown"
    return os.path.join(_LOG_DIR, f"startup_error.{role}.log")


def is_startup_phase():
    with _startup_lock:
        return _startup_phase


def set_startup_role(role):
    """在 clear_startup_logs() 之前调用，决定 startup_error.<role>.log 文件名。"""
    global _startup_role
    _startup_role = (role or "unknown").strip() or "unknown"


def end_startup_phase():
    global _startup_phase
    with _startup_lock:
        _startup_phase = False


def clear_startup_logs():
    """每次进程启动时调用：把两个文件的【内容】截断为 0，保留文件存在。

    - 不删除文件，只清空内容
    - 文件不存在时会被创建为 0 字节
    - startup_error.<role>.log 在启动无错时保持 0 字节
    """
    if not _LOG_DIR_OK:
        return
    with _startup_lock:
        for p in (_STARTUP_LOG_FILE, _startup_error_file()):
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                # 以 "w" 打开即 truncate；文件不存在则创建
                with open(p, "w", encoding="utf-8"):
                    pass
            except Exception:
                pass
        # 清理历史遗留（改名前的旧文件），这个可以删，不是主文件
        try:
            legacy = os.path.join(_LOG_DIR, "_startup.log.bak")
            if os.path.exists(legacy):
                os.remove(legacy)
        except Exception:
            pass


def _write_startup_file(path, text):
    if not _LOG_DIR_OK:
        return
    with _startup_lock:
        try:
            os.makedirs(_LOG_DIR, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass


def log_startup(msg):
    """写启动流水账 → _startup.log。

    - 启动期以外调用：直接 return
    - 每次启动 clear_startup_logs() 已把文件内容截断为 0
    - 不受 config.logging 控制
    - 成功节点、错误节点都写
    """
    if not is_startup_phase():
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    text = f"[{ts}] {msg}\n"
    _write_startup_file(_STARTUP_LOG_FILE, text)
    try:
        print(f"[her_monitor_action_master] {msg}",
              file=sys.stderr, flush=True)
    except Exception:
        pass


def log_startup_error(msg):
    """写启动错误专档 → startup_error.<role>.log。

    - 启动期以外调用：直接 return
    - 每次启动 clear_startup_logs() 已把文件内容截断为 0（文件仍在）
    - 不受 config.logging 控制
    - 不写 _global.log / <agent>.log（错误专档独立）
    """
    if not is_startup_phase():
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    role = _startup_role or "unknown"
    text = f"[{ts}] [{role}] {msg}\n"
    _write_startup_file(_startup_error_file(), text)
    try:
        print(f"[her_monitor_action_master] 启动错误({role}): {msg}",
              file=sys.stderr, flush=True)
    except Exception:
        pass


# ============================================================================
# 常规日志：RotatingFileHandler，256MB × 3
# ============================================================================
def _is_enabled(force=False):
    if force:
        return True
    try:
        from config import get_config
        return get_config().is_logging_enabled()
    except Exception as e:
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
            h = RotatingFileHandler(
                path,
                maxBytes=_MAX_LOG_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
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