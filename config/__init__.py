import os

from .loader import get_config
from .defaults import DEFAULT_CONFIG

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_CONFIG = os.path.join(_PLUGIN_DIR, "config", "master_config.json")

__all__ = ["get_config", "DEFAULT_CONFIG", "MASTER_CONFIG"]