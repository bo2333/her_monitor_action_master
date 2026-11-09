# config/__init__.py
import os

from .loader import get_config
from .defaults import DEFAULT_CONFIG

_HERE = os.path.dirname(os.path.abspath(__file__))
MASTER_CONFIG = os.path.join(os.path.dirname(_HERE), "config", "master_config.json")

__all__ = ["get_config", "DEFAULT_CONFIG", "MASTER_CONFIG"]