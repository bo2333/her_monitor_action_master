from .loader import get_config
from .defaults import DEFAULT_CONFIG

MASTER_CONFIG = __import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.dirname(
        __import__("os").path.abspath(__file__))),
    "config", "master_config.json",
)

__all__ = ["get_config", "DEFAULT_CONFIG", "MASTER_CONFIG"]