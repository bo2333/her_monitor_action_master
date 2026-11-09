# log/__init__.py
from .logger import (
    log, log_error, log_warning,
    set_startup_role, clear_startup_log, log_startup_error,
)

__all__ = [
    "log", "log_error", "log_warning",
    "set_startup_role", "clear_startup_log", "log_startup_error",
]