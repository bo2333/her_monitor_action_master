import logging
import os
import sys
import threading

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PLUGIN_DIR, "logs")

# 启动时立即尝试创建目录；失败打 stderr，不再静默
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
    _LOG_DIR_OK = True
except Exception as _e:
    print(
        f"[monitor_action_master] 无法创建日志目录 {_LOG_DIR}: {_e}，"
        f"将使用 stderr fallback",
        file=sys.stderr,
    )
    _LOG_DIR_OK = False

_logger = logging.getLogger("monitor_action_master")
_logger.setLevel(logging.INFO)
_logger.propagate = False

_handlers = {}
_lock = threading.Lock()


def _is_enabled(force=False):
    if force:
        return True
    try:
        from config import get_config
        return get_config().is_logging_enabled()
    except Exception as e:
        # ★ 关键：config 加载失败时**默认开启**，宁可多写不能静默关闭
        print(
            f"[monitor_action_master] config 加载失败，日志默认开启: {e}",
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
            # ★ 关键：FileHandler 创建失败 → stderr fallback，不静默
            print(
                f"[monitor_action_master] 无法创建日志文件 {path}: {e}，"
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
        # ★ 关键：日志写入失败必须打 stderr，不能吞
        try:
            print(
                f"[monitor_action_master] 日志写入失败: {e}: {msg}",
                file=sys.stderr,
            )
        except Exception:
            pass


def log_error(msg, agent=None):
    log(msg, agent=agent, level=logging.ERROR, force=True)


def log_warning(msg, agent=None):
    log(msg, agent=agent, level=logging.WARNING)