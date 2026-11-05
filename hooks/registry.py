from context import set_current_agent, clear_current_agent
from log import log

HOOKS = [
    ("pre_llm_call",              "on_pre_llm_call"),
    ("post_llm_call",             "on_post_llm_call"),
    ("pre_api_request",           "on_pre_api_request"),
    ("post_api_request",          "on_post_api_request"),
    ("api_request_error",         "on_api_request_error"),
    ("pre_tool_call",             "on_pre_tool_call"),
    ("post_tool_call",            "on_post_tool_call"),
    ("subagent_start",            "on_subagent_start"),
    ("subagent_stop",             "on_subagent_stop"),
    ("pre_approval_request",      "on_pre_approval_request"),
    ("post_approval_response",    "on_post_approval_response"),
    ("pre_auxiliary_call",        "on_pre_auxiliary_call"),
    ("post_auxiliary_call",       "on_post_auxiliary_call"),
    ("session_start",             "on_session_start"),
    ("session_end",               "on_session_end"),
    ("context_compression",       "on_context_compression"),
    ("memory_update",             "on_memory_update"),
    ("on_session_finalize",       "on_session_finalize"),
    ("on_session_reset",          "on_session_reset"),
    ("on_session_delete",         "on_session_delete"),
    ("on_human_input_request",    "on_human_input_request"),
    ("on_human_input_resolved",   "on_human_input_resolved"),
    ("pre_transcription",         "on_pre_transcription"),
    ("pre_verify",                "on_pre_verify"),
    ("on_skill_lifecycle",        "on_skill_lifecycle"),
    ("kanban_task_completed",     "on_kanban_task_completed"),
    ("kanban_task_blocked",       "on_kanban_task_blocked"),
]


def bind_hooks(ctx, handlers, deps_report):
    try:
        agent_name, client = handlers.init_agent_name(ctx)
    except Exception as e:
        log(f"init_agent_name 失败: {e}")
        agent_name, client = "unknown", None

    def bind(fn):
        def wrapped(**kw):
            set_current_agent(agent_name, client)
            try:
                return fn(**kw)
            finally:
                clear_current_agent()
        wrapped.__name__ = getattr(fn, "__name__", "hook")
        wrapped.__qualname__ = getattr(fn, "__qualname__", wrapped.__name__)
        wrapped.__doc__ = getattr(fn, "__doc__", None)
        return wrapped

    ok, fail = 0, 0
    for hook_name, fn_name in HOOKS:
        fn = getattr(handlers, fn_name, None)
        if fn is None:
            log(f"缺少处理函数: {fn_name}（hook: {hook_name}）")
            fail += 1
            continue
        try:
            ctx.register_hook(hook_name, bind(fn))
            ok += 1
        except Exception as e:
            fail += 1
            log(f"Hook 注册失败: {hook_name} -> {e}")
    log(f"register() 完成：成功 {ok} 个，失败 {fail} 个")

    bad = [k for k, v in deps_report.items() if not v]
    if bad:
        log(f"⚠ 依赖缺失：{bad}，相关功能已禁用")