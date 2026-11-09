# 项目根目录 __init__.py
import os as _os
import sys as _sys
import time as _time
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


def _purge_foreign_modules():
    for name in ("deps", "log", "config", "context",
                 "storage", "events", "hooks", "sinks", "status"):
        mod = _sys.modules.get(name)
        if mod is None:
            continue
        f = getattr(mod, "__file__", "") or ""
        d = _os.path.dirname(_os.path.abspath(f)) if f else ""
        if d != _PLUGIN_DIR:
            _sys.modules.pop(name, None)


_purge_foreign_modules()

if _PLUGIN_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGIN_DIR)


def _process_role():
    try:
        with open("/proc/self/cmdline", "rb") as f:
            raw = f.read()
        argv = [a.decode("utf-8", "replace") for a in raw.split(b"\x00") if a]
    except Exception:
        argv = list(_sys.argv)

    for arg in argv:
        if arg == "dashboard":
            return "dashboard"
        if arg == "gateway":
            return "gateway"
    return "cli"


_ROLE = _process_role()


# ★ 加载 log：先设置角色，再清空两个启动文件（_startup.log + startup_error.<role>.log）
from log import (
    log, log_error, log_warning,
    log_startup, log_startup_error,
    clear_startup_logs, set_startup_role, end_startup_phase,
)

set_startup_role(_ROLE)
clear_startup_logs()

# ---- 启动流水账：所有节点都写 _startup.log；错误节点额外写 startup_error.<role>.log ----
log_startup(f"===== 启动开始 role={_ROLE} pid={_os.getpid()} =====")
log_startup(f"插件目录: {_PLUGIN_DIR}")
log_startup(f"Python: {_sys.executable}")
log_startup(f"进程参数: {_sys.argv[1:3]!r}")

log("=" * 60)
log("her_monitor_action_master 加载中")
log(f"角色: {_ROLE}")


# ---- 依赖检查 ----
log_startup("开始依赖检查")
from deps import check as _check_deps
_DEPS_REPORT = _check_deps()
log_startup(f"依赖检查结果: {_DEPS_REPORT}")
log(f"依赖检查结果: {_DEPS_REPORT}")

_bad_deps = [k for k, v in _DEPS_REPORT.items() if not v]
if _bad_deps:
    _msg = f"依赖缺失: {_bad_deps}，相关功能已禁用"
    log_startup(f"⚠ {_msg}")             # 流水账
    log_startup_error(_msg)              # 错误专档
    log_error(_msg, agent="_global")     # 常规日志


# ---- hooks 导入 ----
log_startup("开始导入 hooks")
try:
    from hooks import handlers, registry
    log_startup("hooks 导入成功")
    log("hooks 导入成功")
except Exception as e:
    _msg = f"hooks 导入失败: {e!r}"
    log_startup(f"✗ {_msg}")
    log_startup_error(_msg)
    log_error(_msg, agent="_global")
    log(traceback.format_exc())
    raise


# ---- db_root 检查 ----
def _check_db_root():
    from config import get_config
    try:
        db_root = get_config().get_db_root()
    except Exception as e:
        return False, "", f"读取 db_root 配置失败: {e!r}"

    if not db_root:
        return False, "", "db_root 解析结果为空（异常状态）"

    if not _os.path.exists(db_root):
        try:
            _os.makedirs(db_root, exist_ok=True)
        except PermissionError as e:
            return False, db_root, f"目录不存在且无法创建（权限不足）: {e!r}"
        except OSError as e:
            return False, db_root, f"目录不存在且无法创建（IO 错误）: {e!r}"
        except Exception as e:
            return False, db_root, f"目录不存在且无法创建: {e!r}"

    if not _os.path.isdir(db_root):
        return False, db_root, "路径存在但不是目录"

    try:
        _os.listdir(db_root)
    except PermissionError as e:
        return False, db_root, f"目录不可读（权限不足）: {e!r}"
    except Exception as e:
        return False, db_root, f"目录不可读: {e!r}"

    probe = _os.path.join(
        db_root, f".write_probe_{_os.getpid()}_{int(_time.time() * 1000)}"
    )
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
    except PermissionError as e:
        return False, db_root, f"目录不可写（权限不足）: {e!r}"
    except Exception as e:
        return False, db_root, f"目录不可写: {e!r}"
    finally:
        try:
            _os.remove(probe)
        except Exception:
            pass

    return True, db_root, ""


def _abort_startup(msg):
    full = f"启动失败：{msg}"
    log_startup(f"✗ {full}")             # 流水账
    log_startup_error(full)              # 错误专档
    log_error(full, agent="_global")     # 常规日志
    try:
        end_startup_phase()
    except Exception:
        pass
    raise RuntimeError(f"[her_monitor_action_master] {full}")


def _ensure_db_root_ok():
    log_startup("开始 db_root 检查")
    ok, db_root, err = _check_db_root()
    if not ok:
        _abort_startup(f"db_root 不可用（{db_root or '路径为空'}）：{err}")

    try:
        from config import get_config
        raw = (get_config().snapshot().get("db_root") or "").strip()
        if not raw:
            warn = (
                f"config/master_config.json 未配置 db_root，"
                f"使用默认路径 {db_root}"
            )
            log_startup(f"⚠ {warn}")
            log_startup_error(f"警告：{warn}")
            log(warn, agent="_global", force=True)
    except Exception:
        pass

    log_startup(f"db_root 检查通过: {db_root}")
    log(f"db_root 检查通过: {db_root}", agent="_global", force=True)
    return db_root


# ---- config.set RPC ----
def _handle_config_set(rid, params, key, value, session):
    from config.loader import get_config
    from config import MASTER_CONFIG
    import json

    cfg = get_config()
    new_cfg = cfg.snapshot()

    if isinstance(value, dict):
        if "enabled" in value:
            new_cfg["enabled"] = bool(value["enabled"])
        if "logging" in value:
            new_cfg["logging"] = bool(value["logging"])
        if "db_root" in value:
            new_cfg["db_root"] = str(value["db_root"] or "")
        if "remote" in value and isinstance(value["remote"], dict):
            new_cfg["remote"].update(value["remote"])

    try:
        _os.makedirs(_os.path.dirname(MASTER_CONFIG), exist_ok=True)
        tmp = MASTER_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_cfg, f, ensure_ascii=False, indent=2)
        _os.replace(tmp, MASTER_CONFIG)
    except Exception as e:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32000, "message": f"写入失败: {e}"}}

    cfg.reload()

    try:
        ok, root, err = _check_db_root()
        if not ok:
            log_error(
                f"db_root 变更后检查失败（{root or '空'}）：{err}",
                agent="_global",
            )
        else:
            log(f"db_root 变更后检查通过: {root}", agent="_global", force=True)
    except Exception:
        pass

    return {"jsonrpc": "2.0", "id": rid, "result": {"ok": True, "key": key}}


def _register_config_setter():
    log_startup("开始注册 config.set setter")
    try:
        from tui_gateway.methods_config_set import _CONFIG_SETTERS
        _CONFIG_SETTERS["her_monitor_action_master"] = _handle_config_set
        log_startup("config.set setter 注册成功")
        log("已向 TUI Gateway 注册 config.set setter")
        return True
    except ImportError:
        log_startup("TUI Gateway 不可用，config.set 降级为文件 mtime 热加载")
        log("TUI Gateway 不可用，config.set 降级为文件 mtime 热加载")
        return False
    except Exception as e:
        _msg = f"config.set setter 注册失败: {e!r}"
        log_startup(f"✗ {_msg}")
        log_startup_error(_msg)
        log_error(_msg, agent="_global")
        return False


_RPC_AVAILABLE = _register_config_setter()


# ---- register() ----
def register(ctx):
    log_startup(f"===== register() 进入 role={_ROLE} pid={_os.getpid()} =====")
    print(f"[monitor] register() ENTER pid={_os.getpid()} role={_ROLE} "
          f"argv={_sys.argv[1:3]!r}",
          file=_sys.stderr, flush=True)

    log("=" * 60)
    log("register(ctx) 被调用")

    if getattr(ctx, "_her_monitor_action_registered", False):
        log_startup("⚠ 检测到重复注册，跳过")
        log("⚠ 检测到重复注册，跳过")
        end_startup_phase()
        return
    ctx._her_monitor_action_registered = True

    try:
        _ensure_db_root_ok()

        # ---- init_agent ----
        log_startup("开始 init_agent")
        try:
            agent_name, client = registry.init_agent(ctx, role=_ROLE)
            log_startup(f"init_agent OK agent={agent_name} "
                        f"client={'有' if client else '无'}")
            print(f"[monitor] init_agent OK role={_ROLE} agent={agent_name} "
                  f"client={'有' if client else '无'}",
                  file=_sys.stderr, flush=True)
        except Exception as e:
            _msg = f"init_agent 失败: {e!r}"
            log_startup(f"✗ {_msg}")
            log_startup_error(_msg)
            log_error(_msg, agent="_global")
            print(f"[monitor] init_agent FAIL: {e!r}",
                  file=_sys.stderr, flush=True)
            log(traceback.format_exc())
            agent_name, client = "unknown", None

        # ---- bind_hooks ----
        log_startup("开始 bind_hooks")
        try:
            registry.bind_hooks(ctx, handlers, agent_name, client)
            log_startup("bind_hooks 完成")
        except Exception as e:
            _msg = f"bind_hooks 失败: {e!r}"
            log_startup(f"✗ {_msg}")
            log_startup_error(_msg)
            log_error(_msg, agent="_global")
            log(traceback.format_exc())
            raise

        # ---- write_runtime ----
        log_startup("开始 write_runtime")
        try:
            from status import write_runtime
            from config import get_config
            write_runtime(agent_name, _DEPS_REPORT,
                          get_config().get_db_root(),
                          version="1.2.12",
                          role=_ROLE)
            log_startup("write_runtime 完成")
        except Exception as e:
            _msg = f"write_runtime 失败: {e!r}"
            log_startup(f"✗ {_msg}")
            log_startup_error(_msg)
            log_error(_msg, agent="_global")

        if _bad_deps:
            log(f"⚠ 依赖缺失：{_bad_deps}，相关功能已禁用", agent=agent_name)
    finally:
        log_startup(f"===== register() 完成 role={_ROLE} =====")
        end_startup_phase()
        log(f"register() 启动期结束 role={_ROLE}", agent="_global", force=True)