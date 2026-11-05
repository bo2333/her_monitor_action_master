from log import log
from storage.reader import load_recent


def replay(client, agent_name, max_items=500):
    """把最近事件逐条塞进 client 的发送队列。"""
    rows = load_recent(agent_name, limit=max_items)
    if not rows:
        return
    for r in rows:
        client.send(r)
    log(f"[history] 已入队 {len(rows)} 条", agent=agent_name, force=True)