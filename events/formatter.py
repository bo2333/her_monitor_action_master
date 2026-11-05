# events/formatter.py
import time


def format_event(agent_name, action, flow, conn, level=1, **extra):
    return {
        "ts": int(time.time()),
        "user": agent_name or "unknown",
        "action": str(action),
        "flow": int(flow),
        "conn": str(conn)[:15000],
        "level": str(level),
        "input_tokens": int(extra.get("input_tokens") or 0),
        "output_tokens": int(extra.get("output_tokens") or 0),
        "total_tokens": int(extra.get("total_tokens") or 0),
        "cost": float(extra.get("cost") or 0.0),
    }