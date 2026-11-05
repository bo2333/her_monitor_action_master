import contextvars
import threading

_agent_ctx = contextvars.ContextVar("monitor_agent", default=None)
_client_ctx = contextvars.ContextVar("monitor_client", default=None)
_tls = threading.local()


def set_current_agent(name, client):
    _tls.agent = name
    _tls.client = client
    _agent_ctx.set(name)
    _client_ctx.set(client)


def clear_current_agent():
    _tls.agent = None
    _tls.client = None


def get_current_agent():
    return getattr(_tls, "agent", None) or _agent_ctx.get()


def get_current_client():
    return getattr(_tls, "client", None) or _client_ctx.get()