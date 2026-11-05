import json

from config import get_config
from context import get_current_agent, get_current_client
from events import format_event
from log import log
from storage import Writer

_config = get_config()
_writer = None
_AGENT = "unknown"


def _db_path(agent):
    root = _config.get_db_root()
    return f"{root}/{agent or 'unknown'}.db"


def _get_writer():
    global _writer
    if _writer is None:
        _writer = Writer(_db_path)
    return _writer


def _process_event(action, flow, conn, level=1, **extra):
    if not _config.is_enabled():
        return
    try:
        agent = get_current_agent() or _AGENT
        client = get_current_client()
        data = format_event(agent, action, flow, conn, level, **extra)
        _get_writer().put(data)
        if client is not None:
            client.push(data)
    except Exception as e:
        log(f"处理异常 {action}: {e}")


def _preview(val, limit=1500):
    if val is None:
        return ""
    if isinstance(val, str):
        s = val
    else:
        try:
            s = json.dumps(val, ensure_ascii=False, default=str, check_circular=True)
        except Exception:
            s = str(val)[:limit * 2]
    if len(s) > limit:
        s = s[:limit] + f"\n...[截断，原长 {len(s)}]"
    return s


# ============================================================
# 27 个 observer hook（同上一版，略）
# ============================================================

def on_pre_llm_call(**kw):
    msg = kw.get("user_message") or kw.get("prompt")
    if not msg:
        msgs = kw.get("messages")
        if msgs and isinstance(msgs, list):
            last = msgs[-1]
            if isinstance(last, dict):
                msg = last.get("content", "")
    if msg:
        _process_event("LLM请求", 0, str(msg)[:15000], level=1)


def on_post_llm_call(**kw):
    resp = kw.get("assistant_response") or kw.get("response")
    if resp:
        _process_event("LLM返回", 1, str(resp)[:15000], level=1)


def on_pre_api_request(**kw):
    parts = [f"model={kw.get('model','unknown')}",
             f"provider={kw.get('provider','unknown')}"]
    if kw.get("stream"):
        parts.append("stream=true")
    msgs = kw.get("messages") or []
    if isinstance(msgs, list) and msgs:
        parts.append(f"messages={len(msgs)}")
    _process_event("api_request_start", 0, " | ".join(parts), level=1)


def on_post_api_request(**kw):
    usage = kw.get("usage") or {}
    in_tok = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    out_tok = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    tot_tok = int(usage.get("total_tokens") or (in_tok + out_tok))
    _process_event("api_request", 1,
                   f"model={kw.get('model','unknown')} | in={in_tok} out={out_tok} total={tot_tok}",
                   level=2, input_tokens=in_tok, output_tokens=out_tok, total_tokens=tot_tok)


def on_api_request_error(**kw):
    _process_event("api_error", 1,
                   f"status={kw.get('status_code')} | error={str(kw.get('error'))[:100]}",
                   level=4)


def on_pre_tool_call(**kw):
    name = kw.get("tool_name", "unknown")
    _process_event(f"tool_call:{name}", 0,
                   f"tool: {name} | args: {str(kw.get('arguments') or kw.get('args') or '')[:1000]}",
                   level=1)


def on_post_tool_call(**kw):
    name = kw.get("tool_name", "unknown")
    status = kw.get("status", "unknown")
    _process_event(f"tool_result:{name}", 1,
                   f"status: {status} | result: {str(kw.get('result',''))[:1000]}",
                   level=(1 if status == "ok" else 3))


def on_subagent_start(**kw):
    _process_event("subagent_start", 0,
                   f"role={kw.get('child_role','')} | goal={str(kw.get('child_goal',''))[:200]}",
                   level=1)


def on_subagent_stop(**kw):
    _process_event("subagent_stop", 1,
                   f"role={kw.get('child_role','')} | status={kw.get('child_status','')}",
                   level=1)


def on_pre_approval_request(**kw):
    _process_event("approval_request", 0,
                   f"cmd={str(kw.get('command',''))[:200]}", level=3)


def on_post_approval_response(**kw):
    choice = kw.get("choice", "unknown")
    _process_event("approval_response", 1, f"choice={choice}",
                   level=(1 if choice in ("once", "session", "always") else 4))


def on_pre_auxiliary_call(**kw):
    _process_event("auxiliary_call", 0,
                   f"aux_task={kw.get('aux_task','unknown')}", level=0)


def on_post_auxiliary_call(**kw):
    usage = kw.get("usage") or {}
    in_tok = int(usage.get("prompt_tokens") or 0)
    out_tok = int(usage.get("completion_tokens") or 0)
    tot_tok = int(usage.get("total_tokens") or (in_tok + out_tok))
    _process_event("auxiliary_result", 1,
                   f"aux_task={kw.get('aux_task','unknown')} | in={in_tok} out={out_tok} total={tot_tok}",
                   level=2, input_tokens=in_tok, output_tokens=out_tok, total_tokens=tot_tok)


def on_session_start(**kw):
    _process_event("session_start", 0,
                   f"会话开始 | session: {kw.get('session_id','')}", level=1)


def on_session_end(**kw):
    _process_event("session_end", 1,
                   f"会话结束 | session: {kw.get('session_id','')}", level=1)


def on_context_compression(**kw):
    _process_event("context_compression", 1,
                   f"上下文压缩: {kw.get('old_message_count',0)} -> {kw.get('new_message_count',0)}",
                   level=3)


def on_memory_update(**kw):
    _process_event("memory_update", 0,
                   f"写入记忆 | key: {kw.get('key','')}", level=0)


def on_session_finalize(**kw):
    _process_event("session_finalize", 1,
                   f"会话定稿 | session: {kw.get('session_id','')}", level=1)


def on_session_reset(**kw):
    _process_event("session_reset", 0,
                   f"会话重置 | session: {kw.get('session_id','')}", level=0)


def on_session_delete(**kw):
    _process_event("session_delete", 0,
                   f"会话删除 | session: {kw.get('session_id','')}", level=0)


def on_human_input_request(**kw):
    _process_event("human_input_request", 0,
                   f"prompt: {str(kw.get('prompt', kw.get('question','')))[:300]}",
                   level=3)
    return None


def on_human_input_resolved(**kw):
    _process_event("human_input_resolved", 1,
                   f"value: {str(kw.get('value', kw.get('answer','')))[:300]}",
                   level=1)


def on_pre_transcription(**kw):
    _process_event("pre_transcription", 0,
                   f"source: {kw.get('source', kw.get('audio_path',''))}", level=0)
    return None


def on_pre_verify(**kw):
    _process_event("pre_verify", 0,
                   f"target: {str(kw.get('target',''))[:200]}", level=1)
    return None


def on_skill_lifecycle(**kw):
    _process_event("skill_lifecycle", 0,
                   f"skill: {kw.get('skill','')} | phase: {kw.get('phase','')}",
                   level=0)


def on_kanban_task_completed(**kw):
    _process_event("kanban_task_completed", 1,
                   f"task: {kw.get('task_id','')} | title: {str(kw.get('title',''))[:200]}",
                   level=1)


def on_kanban_task_blocked(**kw):
    _process_event("kanban_task_blocked", 0,
                   f"task: {kw.get('task_id','')} | reason: {str(kw.get('reason',''))[:200]}",
                   level=3)