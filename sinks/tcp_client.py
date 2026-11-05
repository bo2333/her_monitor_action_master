import queue
import socket
import threading
import time
import traceback

from log import log


class TcpClient:
    def __init__(self, agent_name, config):
        self._agent = agent_name
        self._host = config.get("host", "127.0.0.1")
        self._port = int(config.get("port", 9999))
        self._check_interval = int(config.get("check_interval", 60))
        self._q = queue.Queue(maxsize=10000)
        self._sock = None
        self._lock = threading.Lock()
        try:
            import msgpack
            self._packer = msgpack
            log(f"[sink] msgpack OK: {msgpack.__version__} agent={agent_name}")
        except Exception as e:
            log(f"[sink] msgpack 不可用，TCP 推送禁用 agent={agent_name}: {e!r}")
            self._packer = None
            return
        threading.Thread(target=self._loop, daemon=True).start()
        log(f"[sink] _loop 启动 agent={agent_name} target={self._host}:{self._port}")

    def push(self, data):
        if self._packer is None:
            return
        if self._q.qsize() > 100:
            try:
                while not self._q.empty():
                    self._q.get_nowait()
            except queue.Empty:
                pass
        try:
            self._q.put_nowait(data)
        except queue.Full:
            pass

    def _send_history(self, sock):
        """连接后同步历史。依赖 storage 层的查询接口。"""
        try:
            from storage.db import get_connection
            from config import get_config
            db_root = get_config().get_db_root()
            import os
            db_path = os.path.join(db_root, f"{self._agent}.db")
            if not os.path.exists(db_path):
                return
            conn = get_connection(db_path)
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT 500"
            ).fetchall()
            if not rows:
                return
            cols = [d[0] for d in conn.execute(
                "SELECT * FROM events LIMIT 0"
            ).description]
            rows = [dict(zip(cols, r)) for r in reversed(rows)]
            batch = []
            for r in rows:
                batch.append(self._packer.packb({"type": "log", "data": {
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
                }}))
                if len(batch) >= 100:
                    sock.sendall(b"".join(batch))
                    batch.clear()
                    time.sleep(0.02)
            if batch:
                sock.sendall(b"".join(batch))
            log(f"[sink] 历史发送完成 ({len(rows)} 条) agent={self._agent}")
        except Exception as e:
            log(f"[sink] 发送历史失败 agent={self._agent}: {e!r}")

    def _loop(self):
        retry = 0
        while True:
            sock = None
            try:
                log(f"[sink] 尝试连接 {self._host}:{self._port} "
                    f"(retry={retry}) agent={self._agent}")
                sock = socket.create_connection((self._host, self._port), timeout=3)
                sock.setblocking(False)
                log(f"[sink] TCP 已连接 {self._host}:{self._port} agent={self._agent}")

                # 1. hello
                try:
                    sock.sendall(self._packer.packb(
                        {"type": "hello", "user": self._agent}
                    ))
                except Exception as e:
                    log(f"[sink] 发送握手包失败: {e!r}")

                retry = 0
                # 2. 历史
                self._send_history(sock)

                last_send = time.time()
                unpacker = self._packer.Unpacker(max_buffer_size=1 * 1024 * 1024)

                while True:
                    # 3. 实时事件
                    try:
                        item = self._q.get_nowait()
                        try:
                            sock.sendall(self._packer.packb(
                                {"type": "log", "data": item}
                            ))
                            last_send = time.time()
                        except BlockingIOError:
                            self._q.put(item)
                            time.sleep(0.05)
                    except queue.Empty:
                        pass

                    # 4. recv
                    try:
                        chunk = sock.recv(8192)
                        if not chunk:
                            log(f"[sink] 服务端关闭连接 agent={self._agent}")
                            break
                        unpacker.feed(chunk)
                        for _ in unpacker:
                            pass
                    except BlockingIOError:
                        pass
                    except Exception as e:
                        log(f"[sink] recv 异常: {e!r}")
                        break

                    # 5. 心跳
                    if time.time() - last_send > self._check_interval:
                        try:
                            sock.sendall(self._packer.packb(
                                {"action": "__ping__"}
                            ))
                            last_send = time.time()
                        except Exception:
                            break

                    time.sleep(0.1)

            except Exception as e:
                log(f"[sink] 连接失败 {self._host}:{self._port}: {e!r}")
                retry += 1
                delay = min(5 * retry, self._check_interval)
                time.sleep(delay)
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass
                log(f"[sink] 连接关闭 agent={self._agent}")


_clients = {}
_clients_lock = threading.Lock()


def get_client(agent_name, config):
    with _clients_lock:
        if agent_name not in _clients:
            _clients[agent_name] = TcpClient(agent_name, config)
        return _clients[agent_name]