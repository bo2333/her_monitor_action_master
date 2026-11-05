import queue
import socket
import threading
import time

from log import log


class TcpClient:
    def __init__(self, agent_name, config):
        self._agent = agent_name
        self._host = config.get("host", "127.0.0.1")
        self._port = int(config.get("port", 9999))
        self._check = int(config.get("check_interval", 60))
        self._q = queue.Queue(maxsize=10000)
        self._sock = None
        self._lock = threading.Lock()
        try:
            import msgpack
            self._packer = msgpack
            log(f"[sink] msgpack OK agent={agent_name}")
        except Exception as e:
            log(f"[sink] msgpack 不可用，TCP 禁用: {e}")
            self._packer = None
            return
        threading.Thread(target=self._loop, daemon=True).start()
        log(f"[sink] _loop 启动 agent={agent_name} target={self._host}:{self._port}")

    def push(self, data):
        if self._packer is None:
            return
        try:
            self._q.put_nowait(data)
        except queue.Full:
            pass

    def _connect(self):
        try:
            s = socket.create_connection((self._host, self._port), timeout=3)
            s.setblocking(False)
            self._sock = s
            log(f"[sink] 已连接 {self._host}:{self._port}")
            return True
        except Exception as e:
            log(f"[sink] 连接失败 {self._host}:{self._port}: {e}")
            self._sock = None
            return False

    def _loop(self):
        retry = 0
        while True:
            sock = None
            try:
                if not self._connect():
                    retry += 1
                    time.sleep(min(5 * retry, self._check))
                    continue
                sock = self._sock
                sock.sendall(self._packer.packb(
                    {"type": "hello", "user": self._agent}))
                retry = 0
                last = time.time()
                unpacker = self._packer.Unpacker(max_buffer_size=1 << 20)

                while True:
                    try:
                        item = self._q.get_nowait()
                        sock.sendall(self._packer.packb(
                            {"type": "log", "data": item}))
                        last = time.time()
                    except queue.Empty:
                        pass
                    except BlockingIOError:
                        self._q.put(item)
                        time.sleep(0.05)

                    try:
                        chunk = sock.recv(8192)
                        if not chunk:
                            break
                        unpacker.feed(chunk)
                        for _ in unpacker:
                            pass
                    except BlockingIOError:
                        pass
                    except Exception:
                        break

                    if time.time() - last > self._check:
                        try:
                            sock.sendall(self._packer.packb(
                                {"action": "__ping__"}))
                            last = time.time()
                        except Exception:
                            break

                    time.sleep(0.1)
            except Exception as e:
                log(f"[sink] 循环异常: {e}")
                retry += 1
                time.sleep(min(5 * retry, self._check))
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass
                self._sock = None


_clients = {}
_lock = threading.Lock()


def get_client(agent_name, config):
    with _lock:
        if agent_name not in _clients:
            _clients[agent_name] = TcpClient(agent_name, config)
        return _clients[agent_name]