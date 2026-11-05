import os as _os
import sys as _sys
import traceback


def _ensure_site_packages():
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
log("monitor_action_master 加载中")
log(f"依赖检查结果: {_DEPS_REPORT}")

try:
    from hooks import handlers, registry
    log("hooks 导入成功")
except Exception as e:
    log(f"hooks 导入失败: {e}")
    log(traceback.format_exc())
    raise


def _handle_config_set(rid, params, key, value, session):
    from config.loader import get_config
    from config import MASTER_CONFIG
    import json

    cfg = get_config()
    new_cfg = cfg.snapshot()

    if isinstance(value, dict):
        if "enabled" in value:
            new_cfg["enabled"] = bool(value["enabled"])
        if "db_root" in value:
            new_cfg["db_root"] = str(value["db_root"] or "")
        if "remote" in value and isinstance(value["remote"], dict):
            new_cfg["remote"].update(value["remote"])

    try:
        os.makedirs(os.path.dirname(MASTER_CONFIG), exist_ok=True)
        tmp = MASTER_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MASTER_CONFIG)
    except Exception as e:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32000, "message": f"写入失败: {e}"}}

    cfg.reload()
    return {"jsonrpc": "2.0", "id": rid, "result": {"ok": True, "key": key}}


def _register_config_setter():
    try:
        from tui_gateway.methods_config_set import _CONFIG_SETTERS
        _CONFIG_SETTERS["monitor_action_master"] = _handle_config_set
        log("已向 TUI Gateway 注册 config.set setter")
        return True
    except ImportError:
        log("TUI Gateway 不可用，config.set 降级为文件 mtime 热加载")
        return False
    except Exception as e:
        log(f"注册 config.set setter 失败: {e}")
        return False


_RPC_AVAILABLE = _register_config_setter()


def register(ctx):
    log("=" * 60)
    log("register(ctx) 被调用")

    if getattr(ctx, "_monitor_action_registered", False):
        log("⚠ 检测到重复注册，跳过")
        return
    ctx._monitor_action_registered = True

    try:
        agent_name, client = registry.init_agent(ctx)
    except Exception as e:
        log(f"init_agent 失败: {e}")
        log(traceback.format_exc())
        agent_name, client = "unknown", None

    registry.bind_hooks(ctx, handlers, agent_name, client)

    try:
        from status import write_runtime
        from config import get_config
        write_runtime(agent_name, _DEPS_REPORT,
                      get_config().get_db_root(),
                      version="1.2.1")
    except Exception as e:
        log(f"写出 runtime 状态失败: {e}", agent=agent_name)

    bad = [k for k, v in _DEPS_REPORT.items() if not v]
    if bad:
        log(f"⚠ 依赖缺失：{bad}，相关功能已禁用", agent=agent_name)