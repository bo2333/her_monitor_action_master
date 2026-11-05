import queue
import threading
import time

from .db import get_connection


class Writer:
    def __init__(self, db_path_resolver):
        self._q = queue.Queue(maxsize=10000)
        self._resolver = db_path_resolver
        threading.Thread(target=self._loop, daemon=True).start()

    def put(self, data):
        try:
            self._q.put_nowait(data)
        except queue.Full:
            pass

    def _loop(self):
        while True:
            time.sleep(0.5)
            batch = []
            while not self._q.empty() and len(batch) < 500:
                try:
                    batch.append(self._q.get_nowait())
                except queue.Empty:
                    break
            if not batch:
                continue
            try:
                groups = {}
                for d in batch:
                    groups.setdefault(d["user"] or "unknown", []).append(d)
                for agent, items in groups.items():
                    conn = get_connection(self._resolver(agent))
                    for d in items:
                        conn.execute(
                            "INSERT INTO events "
                            "(ts, user, action, flow, conn, level, "
                            "input_tokens, output_tokens, total_tokens, cost) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (d["ts"], d["user"], d["action"], d["flow"],
                             d["conn"], d["level"], d["input_tokens"],
                             d["output_tokens"], d["total_tokens"], d["cost"]),
                        )
                    conn.commit()
            except Exception:
                pass