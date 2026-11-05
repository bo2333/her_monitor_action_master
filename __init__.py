import os as _os
import sys as _sys
import traceback


def _ensure_site_packages():
    """Hermes 若以 -S/-I 启动，site-packages 不在 sys.path。
    用 sys.executable 推导并补进去，幂等，不安装任何东西。"""
    exe = _os.path.realpath(_sys.executable)
    prefix = _os.path.dirname(_os.path.dirname(exe))
    sp = _os.path.join(
        prefix, "lib",
        f"python{_sys.version_info.major}.{_sys.version_info.minor}",
        "site-packages",
    )
    if _os.path.isdir(sp) and sp not in _sys.path:
        _sys.path.append(sp)


_ensure_site_packages()

_PLUGIN_DIR = _os.path.dirname(_os.path.abspath(__file__))
if _PLUGIN_DIR not in _sys.path:
    _sys.path.append(_PLUGIN_DIR)

from deps import check as _check_deps
_DEPS_REPORT = _check_deps()

from log import log

log("=" * 60)
log("__init__.py 顶层代码执行 —— Hermes 已 import 本插件")
log(f"依赖检查结果: {_DEPS_REPORT}")

try:
    from hooks import handlers, registry
    log("hooks 导入成功")
except Exception as e:
    log(f"hooks 导入失败: {e}")
    log(traceback.format_exc())
    raise


def register(ctx):
    log("=" * 60)
    log("register(ctx) 被调用")

    if getattr(ctx, "_monitor_action_registered", False):
        log("⚠ 检测到重复注册，跳过本次绑定")
        return
    ctx._monitor_action_registered = True

    registry.bind_hooks(ctx, handlers, _DEPS_REPORT)