import logging
import os
import threading

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PLUGIN_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_logger = logging.getLogger("monitor_action_master")
_logger.setLevel(logging.INFO)
_logger.propagate = False

_lock = threading.Lock()
_handlers = {}


def _handler_for(agent):
    """每个 Agent 独立日志文件，避免多进程并发写同一文件损坏。"""
    key = agent or "_global"
    with _lock:
        h = _handlers.get(key)
        if h is not None:
            return h
        path = os.path.join(_LOG_DIR, f"{key}.log")
        h = logging.FileHandler(path, encoding="utf-8")
        h.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        _handlers[key] = h
        return h


def log(msg, agent=None, level=logging.INFO):
    try:
        record = _logger.makeRecord(
            _logger.name, level, __file__, 0, str(msg), (), None
        )
        _handler_for(agent).emit(record)
    except Exception:
        pass


def log_error(msg, agent=None):
    log(msg, agent=agent, level=logging.ERROR)


def log_warning(msg, agent=None):
    log(msg, agent=agent, level=logging.WARNING)