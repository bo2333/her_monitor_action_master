import fcntl
import os
import queue
import socket
import sqlite3
import tempfile
import threading
import time

from log import log

_MAX_HISTORY = 500
_RETRY_BASE = 5
_LOOP_TICK = 0.1
_LOCK_RETRY_INTERVAL = 3.0


def _sink_lock_path(agent_name):
    return os.path.join(
        tempfile.gettempdir(),
        f"monitor_action_sink_{agent_name}.lock",
    )


def _try_acquire_sink_lock(agent_name):
    """非阻塞抢跨进程锁。返回 fd 表示成功，None 表示已被其他进程持有。"""
    path = _sink_lock_path(agent_name)
    fd = None
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except (BlockingIOError, OSError):
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        return None


class TcpClient:
    def __init__(self, agent_name, config):
        self.agent_name = agent_name or "unknown"
        self.push_queue = queue.Queue(maxsize=10000)
        self._sock = None
        self._connected = False
        self._last_connect_error = None
        self._last_send_error = None
        self._last_recv_error = None
        self._lock_fd = None

        try:
            import msgpack
            self._msgpack = msgpack
        except Exception as e:
            self._msgpack = None
            log(f"[sink] msgpack 不可用，TCP 禁用: {e!r}", agent=self.agent_name)
            return

        threading.Thread(target=self._loop, daemon=True).start()

    # ---- 内部 ----
    def _get_remote(self):
        from config import get_config
        return get_config().get_remote()

    def _get_db_root(self):
        from config import get_config
        return get_config().get_db_root()

    def _acquire_lock_blocking(self):
        """阻塞直到抢到跨进程推送锁；每 3 秒重试一次。"""
        if self._lock_fd is not None:
            return
        while True:
            fd = _try_acquire_sink_lock(self.agent_name)
            if fd is not None:
                self._lock_fd = fd
                log(f"[sink] 获得推送锁 pid={os.getpid()} agent={self.agent_name}",
                    agent=self.agent_name)
                return
            log(f"[sink] 等待另一进程释放 {self.agent_name} 的推送锁，"
                f"{int(_LOCK_RETRY_INTERVAL)}s 后重试", agent=self.agent_name)
            time.sleep(_LOCK_RETRY_INTERVAL)

    # ---- 对外 ----
    def push(self, data):
        if self._msgpack is None:
            return
        try:
            self.push_queue.put_nowait(data)
        except queue.Full:
            pass

    # ---- 历史回放 ----
    def _send_history(self, sock):
        try:
            db_path = os.path.join(self._get_db_root(), f"{self.agent_name}.db")
        except Exception as e:
            log(f"[sink] 获取 DB 路径失败: {e!r}", agent=self.agent_name)
            return
        if not os.path.exists(db_path):
            return

        rows = []
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (_MAX_HISTORY,),
            ).fetchall()
        except Exception as e:
            log(f"[sink] 读取历史失败: {e!r}", agent=self.agent_name)
            return
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        if not rows:
            return

        rows = [dict(r) for r in reversed(rows)]

        try:
            sock.setblocking(True)
            sock.settimeout(5.0)
            batch = []
            for r in rows:
                item = {
                    "ts": int(r.get("ts") or time.time()),
                    "user": str(r.get("user") or "unknown"),
                    "flow": int(r.get("flow") or 0),
                    "conn": str(r.get("conn") or ""),
                    "action": str(r.get("action") or ""),
                    "level": str(r.get("level") or ""),
                    "input_tokens": int(r.get("input_tokens") or 0),
                    "output_tokens": int(r.get("output_tokens") or 0),
                    "total_tokens": int(r.get("total_tokens") or 0),
                    "cost": float(r.get("cost") or 0.0),
                }
                batch.append(self._msgpack.packb({"type": "log", "data": item}))
                if len(batch) >= 100:
                    sock.sendall(b"".join(batch))
                    batch.clear()
                    time.sleep(0.02)
            if batch:
                sock.sendall(b"".join(batch))
            log(f"[sink] 历史发送完成 ({len(rows)} 条)", agent=self.agent_name)
        except Exception as e:
            log(f"[sink] 发送历史失败: {e!r}", agent=self.agent_name)
        finally:
            try:
                sock.setblocking(False)
            except Exception:
                pass

    # ---- 主循环 ----
    def _loop(self):
        # ★ 先抢跨进程锁，抢到才进入 TCP 循环
        self._acquire_lock_blocking()

        retry_count = 0
        while True:
            remote = self._get_remote()
            if not remote.get("enabled") or self._msgpack is None:
                time.sleep(5)
                continue

            host = remote.get("host", "127.0.0.1")
            port = int(remote.get("port", 9999))
            check_interval = int(remote.get("check_interval", 60))
            sock = None
            try:
                sock = socket.create_connection((host, port), timeout=3)
                sock.setblocking(False)
                if not self._connected:
                    log(f"[sink] 已连接 {host}:{port}", agent=self.agent_name)
                    self._connected = True
                    self._last_connect_error = None

                try:
                    hello_msg = self._msgpack.packb(
                        {"type": "hello", "user": self.agent_name}
                    )
                    sock.sendall(hello_msg)
                except Exception as e:
                    if repr(e) != self._last_send_error:
                        log(f"[sink] 发送握手失败: {e!r}", agent=self.agent_name)
                        self._last_send_error = repr(e)

                retry_count = 0
                self._send_history(sock)
                last_send_time = time.time()
                unpacker = self._msgpack.Unpacker(max_buffer_size=1 << 20)

                while True:
                    now = self._get_remote()
                    if (not now.get("enabled")
                            or now.get("host") != host
                            or int(now.get("port")) != port):
                        log(f"[sink] 配置变更，断开重连", agent=self.agent_name)
                        break

                    try:
                        item = self.push_queue.get_nowait()
                        try:
                            sock.sendall(self._msgpack.packb(
                                {"type": "log", "data": item}
                            ))
                            last_send_time = time.time()
                        except BlockingIOError:
                            self.push_queue.put(item)
                            time.sleep(0.05)
                    except queue.Empty:
                        pass

                    try:
                        chunk = sock.recv(8192)
                        if not chunk:
                            log(f"[sink] 服务端关闭连接", agent=self.agent_name)
                            break
                        unpacker.feed(chunk)
                        for _ in unpacker:
                            pass
                    except BlockingIOError:
                        pass
                    except Exception as e:
                        if repr(e) != self._last_recv_error:
                            log(f"[sink] recv 异常: {e!r}", agent=self.agent_name)
                            self._last_recv_error = repr(e)
                        break

                    if time.time() - last_send_time > check_interval:
                        try:
                            sock.sendall(self._msgpack.packb(
                                {"action": "__ping__"}
                            ))
                            last_send_time = time.time()
                        except Exception:
                            break

                    time.sleep(_LOOP_TICK)

            except Exception as e:
                msg = repr(e)
                if msg != self._last_connect_error:
                    log(f"[sink] 连接失败 {host}:{port}: {msg}",
                        agent=self.agent_name)
                    self._last_connect_error = msg
                self._connected = False
                retry_count += 1
                delay = min(_RETRY_BASE * retry_count, check_interval)
                time.sleep(delay)
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass
                self._connected = False


_clients = {}
_clients_lock = threading.Lock()


def get_client(agent_name, config):
    agent_name = agent_name or "unknown"
    with _clients_lock:
        if agent_name not in _clients:
            _clients[agent_name] = TcpClient(agent_name, config)
        return _clients[agent_name]