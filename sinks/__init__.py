# sinks/__init__.py
from .tcp_client import get_client

__all__ = ["get_client"]