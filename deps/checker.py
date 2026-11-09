import importlib
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_FILE = os.path.join(_PLUGIN_DIR, "logs", "deps.log")

_REQUIRED = {
    "msgpack": "msgpack>=1.0",
}


def _can_import(mod):
    if mod in sys.modules:
        return True
    importlib.invalidate_caches()
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def check():
    """只检查依赖，缺失时写 deps.log 给出修复命令，不执行安装。"""
    report = {mod: _can_import(mod) for mod in _REQUIRED}
    missing = [m for m, ok in report.items() if not ok]
    if not missing:
        return report

    specs = " ".join(f'"{_REQUIRED[m]}"' for m in missing)
    lines = [
        f"=== 依赖缺失: {missing} ===",
        f"sys.executable = {sys.executable}",
        "修复方式（任选其一）：",
        "  1) 官方：hermes plugins enable her_monitor_action_master",
        f"  2) 手动：{sys.executable} -m pip install {specs}",
    ]
    try:
        import time
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            for line in lines:
                f.write(f"[{ts}] {line}\n")
    except Exception:
        pass

    # stdout 是给 Hermes 的 stderr 通道看到，不影响落盘
    print("\n".join(lines), file=sys.stderr, flush=True)
    return report