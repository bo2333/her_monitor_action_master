import logging
import os

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PLUGIN_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "plugin.log")

_logger = logging.getLogger("monitor_action_master")
_logger.setLevel(logging.INFO)
_logger.propagate = False

if not _logger.handlers:
    _handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    _handler.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(_handler)


def log(msg, agent=None, level=logging.INFO):
    prefix = f"[{agent}] " if agent else ""
    _logger.log(level, prefix + str(msg))


def log_error(msg, agent=None):
    log(msg, agent=agent, level=logging.ERROR)


def log_warning(msg, agent=None):
    log(msg, agent=agent, level=logging.WARNING)