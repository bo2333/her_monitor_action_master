import logging

_logger = logging.getLogger("monitor_action_master")

# 若 Hermes 已配置 root logger，则沿用；否则加一个 fallback
if not _logger.handlers and not logging.getLogger().handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(_handler)

_logger.setLevel(logging.INFO)


def log(msg, agent=None, level=logging.INFO):
    prefix = f"[{agent}] " if agent else ""
    _logger.log(level, prefix + str(msg))


def log_error(msg, agent=None):
    log(msg, agent=agent, level=logging.ERROR)


def log_warning(msg, agent=None):
    log(msg, agent=agent, level=logging.WARNING)