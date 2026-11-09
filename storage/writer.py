import os
import queue
import sqlite3
import threading
import time
import traceback

from log import log, log_error
from .db import get_connection, invalidate_connection

_CHECKPOINT_EVERY_N_BATCH = 40
_STATS_INTERVAL = 30.0
_LOCKED_RETRY_TIMES = 3
_LOCKED_RETRY_SLEEP = 1.0
_LOOP_RESTART_SLEEP = 2.0        # ★ 线程级异常后的重启间隔


def _safe_int(v, default=0):
    try:
        return default if v is None else int(v)
    except (ValueError, TypeError):
        return default


def _safe_float(v, default=0.0):
    try:
        return default if v is None else float(v)
    except (ValueError, TypeError):
        return default


class Writer:
    def __init__(self, db_path_resolver):
        self._q = queue.Queue(maxsize=10000)
        self._resolver = db_path_resolver
        self._stats = {}
        self._stats_lock = threading.Lock()
        self._pid = os.getpid()
        # ★ 记录线程级异常次数，供外部观察
        self._loop_restarts = 0
        self._last_loop_error = None
        threading.Thread(target=self._loop_entry, daemon=True,
                         name="monitor-writer").start()

    def put(self, data):
        try:
            self._q.put_nowait(data)
        except queue.Full:
            agent = (data.get("user") if isinstance(data, dict) else None) or "unknown"
            self._inc_stats(agent, "dropped")

    def _inc_stats(self, agent, field, n=1):
        with self._stats_lock:
            s = self._stats.setdefault(
                agent, {"written": 0, "errors": 0, "dropped": 0, "retried": 0}
            )
            s[field] += n

    def _flush_stats(self):
        with self._stats_lock:
            snapshot = dict(self._stats)
            self._stats = {}
        for agent, s in snapshot.items():
            parts = [f"{k}={s[k]}" for k in
                     ("written", "errors", "dropped", "retried")
                     if s.get(k)]
            if parts:
                # ★ dropped / errors 用 log_error（force=True 穿透 logging 开关）
                if s.get("errors") or s.get("dropped"):
                    log_error(f"[writer] {agent} pid={self._pid} " + " ".join(parts),
                              agent=agent)
                else:
                    log(f"[writer] {agent} pid={self._pid} " + " ".join(parts),
                        agent=agent)

    def _normalize(self, d):
        return {
            "ts": _safe_int(d.get("ts"), int(time.time())),
            "user": str(d.get("user") or "unknown"),
            "action": str(d.get("action") or ""),
            "flow": _safe_int(d.get("flow")),
            "conn": str(d.get("conn") or ""),
            "level": str(d.get("level") or ""),
            "input_tokens": _safe_int(
                d.get("input_tokens", d.get("in_tok"))),
            "output_tokens": _safe_int(
                d.get("output_tokens", d.get("out_tok"))),
            "total_tokens": _safe_int(
                d.get("total_tokens", d.get("tot_tok"))),
            "cost": _safe_float(d.get("cost")),
            "pid": self._pid,
        }

    def _write_group(self, agent, items):
        # ★ 修复：resolver 和 get_connection 包在 try 里
        try:
            db_path = self._resolver(agent)
        except Exception as e:
            self._inc_stats(agent, "errors", len(items))
            log_error(f"[writer] {agent} pid={self._pid} "
                      f"解析 db_path 失败，本批 {len(items)} 条丢弃: {e!r}",
                      agent=agent)
            log(traceback.format_exc(), agent=agent)
            return False

        try:
            conn = get_connection(db_path)
        except Exception as e:
            self._inc_stats(agent, "errors", len(items))
            log_error(f"[writer] {agent} pid={self._pid} "
                      f"打开 db 失败 {db_path}，本批 {len(items)} 条丢弃: {e!r}",
                      agent=agent)
            log(traceback.format_exc(), agent=agent)
            # 确保缓存里没有坏连接
            try:
                invalidate_connection(db_path)
            except Exception:
                pass
            return False

        for attempt in range(1, _LOCKED_RETRY_TIMES + 1):
            try:
                for d in items:
                    conn.execute(
                        "INSERT INTO events "
                        "(ts, user, action, flow, conn, level, "
                        "input_tokens, output_tokens, total_tokens, cost, pid) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (d["ts"], d["user"], d["action"], d["flow"],
                         d["conn"], d["level"], d["input_tokens"],
                         d["output_tokens"], d["total_tokens"], d["cost"],
                         d["pid"]),
                    )
                conn.commit()
                self._inc_stats(agent, "written", len(items))
                return True

            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                try:
                    conn.rollback()
                except Exception:
                    pass

                if "locked" in msg or "busy" in msg:
                    self._inc_stats(agent, "retried", len(items))
                    if attempt < _LOCKED_RETRY_TIMES:
                        time.sleep(_LOCKED_RETRY_SLEEP)
                        continue
                    self._inc_stats(agent, "errors", len(items))
                    log_error(
                        f"[writer] {agent} pid={self._pid} "
                        f"database locked 重试耗尽，本批 {len(items)} 条丢弃",
                        agent=agent)
                    return False

                self._inc_stats(agent, "errors", len(items))
                log_error(f"[writer] {agent} pid={self._pid} "
                          f"写入失败（非锁冲突）: {e!r}", agent=agent)
                log(traceback.format_exc(), agent=agent)
                invalidate_connection(db_path)
                return False

            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                self._inc_stats(agent, "errors", len(items))
                log_error(f"[writer] {agent} pid={self._pid} "
                          f"写入失败: {e!r}", agent=agent)
                log(traceback.format_exc(), agent=agent)
                invalidate_connection(db_path)
                return False

        return False

    # ========================================================================
    # ★ 新增：线程级入口，包住 _loop 所有异常，崩溃自动重启
    # ========================================================================
    def _loop_entry(self):
        while True:
            try:
                self._loop()
                # _loop 正常应该永不返回；返回了说明被 break 了，重启
                log_error(f"[writer] pid={self._pid} _loop 意外返回，"
                          f"{_LOOP_RESTART_SLEEP}s 后重启",
                          agent="_global")
            except Exception as e:
                self._loop_restarts += 1
                self._last_loop_error = repr(e)
                log_error(f"[writer] pid={self._pid} _loop 线程崩溃 "
                          f"(第 {self._loop_restarts} 次)，"
                          f"{_LOOP_RESTART_SLEEP}s 后重启: {e!r}",
                          agent="_global")
                log(traceback.format_exc(), agent="_global")
            time.sleep(_LOOP_RESTART_SLEEP)

    def _loop(self):
        batch_counter = 0
        last_flush = time.time()
        while True:
            time.sleep(0.5)
            if time.time() - last_flush >= _STATS_INTERVAL:
                try:
                    self._flush_stats()
                except Exception as e:
                    log_error(f"[writer] _flush_stats 异常: {e!r}",
                              agent="_global")
                last_flush = time.time()

            batch = []
            while not self._q.empty() and len(batch) < 500:
                try:
                    batch.append(self._q.get_nowait())
                except queue.Empty:
                    break
            if not batch:
                continue

            groups = {}
            for d in batch:
                try:
                    nd = self._normalize(d)
                except Exception:
                    continue
                groups.setdefault(nd["user"], []).append(nd)

            touched = {}
            for agent, items in groups.items():
                try:
                    touched[agent] = self._resolver(agent)
                except Exception:
                    pass
                # ★ _write_group 已经内部 try 全部，这里再加一层防御
                try:
                    self._write_group(agent, items)
                except Exception as e:
                    log_error(f"[writer] _write_group 意外异常 {agent}: {e!r}",
                              agent=agent)
                    log(traceback.format_exc(), agent=agent)

            batch_counter += 1
            if batch_counter >= _CHECKPOINT_EVERY_N_BATCH:
                batch_counter = 0
                for agent, db_path in touched.items():
                    try:
                        get_connection(db_path).execute(
                            "PRAGMA wal_checkpoint(PASSIVE)")
                    except Exception:
                        pass