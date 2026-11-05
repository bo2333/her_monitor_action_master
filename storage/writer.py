import queue
import threading
import time
import traceback

from log import log
from .db import get_connection

_CHECKPOINT_EVERY_N_BATCH = 40
_STATS_INTERVAL = 30.0


class Writer:
    def __init__(self, db_path_resolver):
        self._q = queue.Queue(maxsize=10000)
        self._resolver = db_path_resolver
        self._stats = {}
        self._stats_lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def put(self, data):
        try:
            self._q.put_nowait(data)
        except queue.Full:
            agent = (data.get("user") if isinstance(data, dict) else None) or "unknown"
            self._inc_stats(agent, "dropped")

    def _inc_stats(self, agent, field, n=1):
        with self._stats_lock:
            s = self._stats.setdefault(
                agent, {"written": 0, "errors": 0, "dropped": 0}
            )
            s[field] += n

    def _flush_stats(self):
        with self._stats_lock:
            snapshot = dict(self._stats)
            self._stats = {}
        for agent, s in snapshot.items():
            parts = []
            if s["written"]:
                parts.append(f"written={s['written']}")
            if s["errors"]:
                parts.append(f"errors={s['errors']}")
            if s["dropped"]:
                parts.append(f"dropped={s['dropped']}")
            if parts:
                log(f"[writer] {agent} " + " ".join(parts), agent=agent)

    def _normalize(self, d):
        return {
            "ts": int(d.get("ts") or time.time()),
            "user": str(d.get("user") or "unknown"),
            "action": str(d.get("action") or ""),
            "flow": int(d.get("flow") or 0),
            "conn": str(d.get("conn") or ""),
            "level": str(d.get("level") or ""),
            "input_tokens": int(d.get("input_tokens", d.get("in_tok", 0)) or 0),
            "output_tokens": int(d.get("output_tokens", d.get("out_tok", 0)) or 0),
            "total_tokens": int(d.get("total_tokens", d.get("tot_tok", 0)) or 0),
            "cost": float(d.get("cost", 0.0) or 0.0),
        }

    def _loop(self):
        batch_counter = 0
        last_flush = time.time()
        while True:
            time.sleep(0.5)

            if time.time() - last_flush >= _STATS_INTERVAL:
                self._flush_stats()
                last_flush = time.time()

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
                    nd = self._normalize(d)
                    groups.setdefault(nd["user"], []).append(nd)

                touched = {}
                for agent, items in groups.items():
                    try:
                        db_path = self._resolver(agent)
                        conn = get_connection(db_path)
                        touched[agent] = conn
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
                        self._inc_stats(agent, "written", len(items))
                    except Exception as e:
                        self._inc_stats(agent, "errors", len(items))
                        log(f"[writer] {agent} 写入失败: {e!r}", agent=agent)
                        log(traceback.format_exc(), agent=agent)

                batch_counter += 1
                if batch_counter >= _CHECKPOINT_EVERY_N_BATCH:
                    batch_counter = 0
                    for agent, conn in touched.items():
                        try:
                            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                        except Exception:
                            pass
            except Exception as e:
                log(f"[writer] 批处理失败: {e!r}")
                log(traceback.format_exc())