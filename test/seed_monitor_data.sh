#!/usr/bin/env bash
# =============================================================================
# her_monitor_action_master 测试数据生成脚本
#
# 位置：test/seed_monitor_data.sh
# 本目录（test/）仅存放开发期测试用脚本，不随插件运行时加载，不影响生产。
#
# 用途：
#   1. 往 db_root 下的 {agent}.db 写入覆盖全部 27+ 种 action 的测试事件
#   2. 覆盖不同 level（0-4）、flow（0/1）、tokens、cost、时间跨度（1h/3d/15d/60d）
#   3. 包含 JSON / Markdown / tool_result / 超长文本等 conn 格式，测试 booth 的 parsers
#   4. （可选 -s）生成 status/*.json，测试 booth 状态面板的三态显示
#
# 用法：
#   ./test/seed_monitor_data.sh                    # 默认参数，追加模式
#   ./test/seed_monitor_data.sh -c                 # 先清空已有 .db
#   ./test/seed_monitor_data.sh -a default -n 2    # 只写 default，每种 action 2 条
#   ./test/seed_monitor_data.sh -s                 # 同时生成 status 测试文件
#   ./test/seed_monitor_data.sh -d /root/Data/her_monitor_action_master
# =============================================================================

set -euo pipefail

# ---------------- 默认值 ----------------
DB_ROOT=""
AGENTS="default,agent_a,agent_b"
PER_ACTION=4
HOURS_BACK=168
DO_CLEAN=0
DO_STATUS=0
MASTER_DIR=""

usage() {
    cat <<EOF
用法: $(basename "$0") [选项]

选项:
  -d, --db-root PATH      指定 db_root（默认从 master_config.json 读，兜底 <master>/data）
  -a, --agents LIST       要生成的 agent 名，逗号分隔（默认: $AGENTS）
  -n, --per-action N      每个 action 生成 N 条（默认: $PER_ACTION，N>=1）
  -b, --hours-back H      数据时间跨度的最大回溯小时数（默认: $HOURS_BACK）
  -c, --clean             先清空已存在的 {agent}.db
  -s, --status            同时生成 status/*.json（测三态显示）
  -m, --master-dir DIR    指定 master 插件目录（默认从脚本位置推导）
  -h, --help              显示此帮助

示例:
  $(basename "$0") -c -n 2 -a default
  $(basename "$0") -s -a default,agent_a -n 4
EOF
}

# ---------------- 解析参数 ----------------
while [ $# -gt 0 ]; do
    case "$1" in
        -d|--db-root)     DB_ROOT="$2";       shift 2 ;;
        -a|--agents)      AGENTS="$2";        shift 2 ;;
        -n|--per-action)  PER_ACTION="$2";    shift 2 ;;
        -b|--hours-back)  HOURS_BACK="$2";    shift 2 ;;
        -c|--clean)       DO_CLEAN=1;         shift ;;
        -s|--status)      DO_STATUS=1;        shift ;;
        -m|--master-dir)  MASTER_DIR="$2";    shift 2 ;;
        -h|--help)        usage; exit 0 ;;
        *) echo "未知参数: $1" >&2; usage; exit 1 ;;
    esac
done

# ---------------- 定位 master 目录 ----------------
# 脚本在 <master>/test/ 下，向上一级即 master 根目录
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -z "$MASTER_DIR" ]; then
    if [ -f "$SCRIPT_DIR/../plugin.yaml" ]; then
        MASTER_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
    else
        echo "✗ 无法定位 master 目录（找不到 $SCRIPT_DIR/../plugin.yaml），请用 -m 指定" >&2
        exit 1
    fi
fi
echo "→ master 目录: $MASTER_DIR"

# ---------------- 定位 db_root ----------------
if [ -z "$DB_ROOT" ]; then
    MASTER_CONFIG="$MASTER_DIR/config/master_config.json"
    if [ -f "$MASTER_CONFIG" ]; then
        if command -v python3 >/dev/null 2>&1; then
            DB_ROOT=$(python3 -c \
                "import json; print((json.load(open('$MASTER_CONFIG')).get('db_root') or '').strip())" \
                2>/dev/null || true)
        else
            DB_ROOT=$(grep -o '"db_root"[[:space:]]*:[[:space:]]*"[^"]*"' "$MASTER_CONFIG" \
                2>/dev/null | head -1 | sed 's/.*"[[:space:]]*:[[:space:]]*"\(.*\)"/\1/' || true)
        fi
    fi
    if [ -z "$DB_ROOT" ]; then
        DB_ROOT="$MASTER_DIR/data"
        echo "→ master_config.json 中 db_root 为空，使用默认: $DB_ROOT"
    fi
fi
echo "→ db_root: $DB_ROOT"

# ---------------- 前置检查 ----------------
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "✗ 找不到 sqlite3 命令，请先安装: apt-get install -y sqlite3" >&2
    exit 1
fi

mkdir -p "$DB_ROOT"

# ---------------- schema（与 master/storage/schema.sql 完全一致） ----------------
SCHEMA_SQL=$(cat <<'SQL'
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             INTEGER NOT NULL,
    user           TEXT    NOT NULL,
    action         TEXT    NOT NULL,
    flow           INTEGER NOT NULL,
    conn           TEXT    NOT NULL,
    level          TEXT    DEFAULT '',
    input_tokens   INTEGER DEFAULT 0,
    output_tokens  INTEGER DEFAULT 0,
    total_tokens   INTEGER DEFAULT 0,
    cost           REAL    DEFAULT 0.0,
    pid            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
SQL
)

# ---------------- 时间戳分布 ----------------
# 4 档时间桶，用于测试 token 趋势的 period（今日/本周/本月/总计）
NOW=$(date +%s)
TS_BUCKETS=(
    "$(( NOW - 3600 ))"               # 1 小时前
    "$(( NOW - 3 * 86400 ))"          # 3 天前
    "$(( NOW - 15 * 86400 ))"         # 15 天前
    "$(( NOW - 60 * 86400 ))"         # 60 天前
)

# ---------------- 行生成函数 ----------------
# gen_row ts user action flow conn level in out total cost pid
gen_row() {
    local ts=$1 user=$2 action=$3 flow=$4 conn=$5 level=$6
    local in_t=$7 out_t=$8 tot_t=$9 cost=${10} pid=${11}
    local conn_esc="${conn//\'/\'\'}"
    printf "INSERT INTO events (ts,user,action,flow,conn,level,input_tokens,output_tokens,total_tokens,cost,pid) VALUES (%d,'%s','%s',%d,'%s','%s',%d,%d,%d,%s,%d);\n" \
        "$ts" "$user" "$action" "$flow" "$conn_esc" "$level" \
        "$in_t" "$out_t" "$tot_t" "$cost" "$pid"
}

# emit_actions ts user pid idx —— 一次生成该时间点下的一整套事件
emit_actions() {
    local ts=$1 user=$2 pid=$3 idx=$4
    local uniq="${user}_${idx}_${ts}"
    local sess="sess_${uniq}"
    local long_text
    long_text=$(head -c 16000 /dev/zero | tr '\0' 'A')

    # ---- 会话生命周期 ----
    gen_row "$ts" "$user" "session_start"        0 "会话开始 | session: $sess"              "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "session_finalize"     1 "会话定稿 | session: $sess"              "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "session_end"          1 "会话结束 | session: $sess"              "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "session_reset"        0 "会话重置 | session: $sess"              "0" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "session_delete"       0 "会话删除 | session: $sess"              "0" 0 0 0 "0.0" "$pid"

    # ---- LLM / API ----
    gen_row "$ts" "$user" "LLM请求"              0 "用户提问：请检查 ${uniq} 的运行日志"      "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "LLM返回"              1 "好的，这是第 ${idx} 次分析结果。"           "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "api_request_start"    0 "model=gpt-4 | provider=openai | messages=3" "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "api_request"          1 "model=gpt-4 | in=1200 out=350 total=1550"   "2" 1200 350 1550 "0.0231" "$pid"
    gen_row "$ts" "$user" "api_error"            1 "status=429 | error=rate limit exceeded"      "4" 0 0 0 "0.0" "$pid"

    # ---- 工具 ----
    gen_row "$ts" "$user" "tool_call:bash"       0 "tool: bash | args: ls -la /tmp"                        "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "tool_result:bash"     1 'status: ok | result: {"content": "total 0"}'           "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "tool_result:read"     1 'status: error | result: {"error": "file not found"}'   "3" 0 0 0 "0.0" "$pid"

    # ---- 子代理 / 审批 / 辅助 ----
    gen_row "$ts" "$user" "subagent_start"       0 "role=researcher | goal=分析日志"       "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "subagent_stop"        1 "role=researcher | status=ok"          "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "approval_request"     0 "cmd=rm -rf /tmp/test"                  "3" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "approval_response"    1 "choice=once"                           "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "auxiliary_call"       0 "aux_task=summarize"                    "0" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "auxiliary_result"     1 "aux_task=summarize | in=500 out=80 total=580" "2" 500 80 580 "0.0023" "$pid"

    # ---- 上下文 / 记忆 / 人工 / 其它 ----
    gen_row "$ts" "$user" "context_compression"  1 "上下文压缩: 45 -> 20"                     "3" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "memory_update"        0 "写入记忆 | key=session_${uniq}"           "0" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "human_input_request"  0 "prompt: 请确认是否继续执行？"              "3" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "human_input_resolved" 1 "value: yes"                              "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "pre_transcription"    0 "source: /tmp/audio.wav"                  "0" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "pre_verify"           0 "target: main.py"                         "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "skill_lifecycle"      0 "skill=code_review | phase=start"         "0" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "kanban_task_completed" 1 "task=t_${uniq} | title=修复登录 bug"    "1" 0 0 0 "0.0" "$pid"
    gen_row "$ts" "$user" "kanban_task_blocked"  0 "task=t_${uniq}_2 | reason=等待审批"       "3" 0 0 0 "0.0" "$pid"

    # ---- 测试 parsers.js 的特殊 conn 格式 ----
    # JSON 对象（触发 renderJsonObject）
    gen_row "$ts" "$user" "api_request" 1 \
        '{"output": "这是 JSON 格式输出", "model": "claude-3", "in_tok": 800, "out_tok": 200}' \
        "2" 800 200 1000 "0.0150" "$pid"

    # Markdown（触发 markdownToHtml）
    gen_row "$ts" "$user" "LLM返回" 1 \
        '**加粗** 和 `code` 以及列表:\n- item1\n- item2\n- item3' \
        "1" 0 0 0 "0.0" "$pid"

    # 超长文本（测试 15000+ 边界）
    gen_row "$ts" "$user" "LLM请求" 0 "$long_text" "1" 0 0 0 "0.0" "$pid"
}

# ---------------- 对每个 agent 写入 ----------------
IFS=',' read -ra AGENT_LIST <<< "$AGENTS"
TOTAL_AGENTS=0
TOTAL_ROWS=0

for agent in "${AGENT_LIST[@]}"; do
    agent=$(echo "$agent" | xargs)
    [ -z "$agent" ] && continue

    db_path="$DB_ROOT/${agent}.db"
    echo ""
    echo "==> [$agent] → $db_path"

    if [ "$DO_CLEAN" -eq 1 ]; then
        rm -f "$db_path" "${db_path}-wal" "${db_path}-shm"
        echo "    已清空旧数据"
    fi

    # 建表（幂等）
    sqlite3 "$db_path" <<< "$SCHEMA_SQL"

    # 生成 SQL 到临时文件
    tmp_sql=$(mktemp)
    tmp_final=$(mktemp)
    trap 'rm -f "$tmp_sql" "$tmp_final"' RETURN

    rows_this=0
    for i in $(seq 1 "$PER_ACTION"); do
        ts_idx=$(( (i - 1) % ${#TS_BUCKETS[@]} ))
        ts=${TS_BUCKETS[$ts_idx]}
        pid=$(( 1000 + RANDOM % 9000 ))
        emit_actions "$ts" "$agent" "$pid" "$i" >> "$tmp_sql"
        rows_this=$(( rows_this + 31 ))
    done

    {
        echo "BEGIN;"
        cat "$tmp_sql"
        echo "COMMIT;"
    } > "$tmp_final"

    if ! sqlite3 "$db_path" < "$tmp_final"; then
        echo "    ✗ 写入失败" >&2
        rm -f "$tmp_sql" "$tmp_final"
        exit 1
    fi
    rm -f "$tmp_sql" "$tmp_final"

    count=$(sqlite3 "$db_path" "SELECT COUNT(*) FROM events;")
    echo "    写入完成：本次 $rows_this 条，库内共 $count 条"

    TOTAL_AGENTS=$(( TOTAL_AGENTS + 1 ))
    TOTAL_ROWS=$(( TOTAL_ROWS + rows_this ))
done

# ---------------- status 文件（可选） ----------------
ALIVE_PID=""
ALIVE_PID2=""
trap 'kill ${ALIVE_PID:-} ${ALIVE_PID2:-} 2>/dev/null || true' EXIT

if [ "$DO_STATUS" -eq 1 ]; then
    STATUS_DIR="$MASTER_DIR/status"
    mkdir -p "$STATUS_DIR"
    echo ""
    echo "==> 生成 status 测试文件 → $STATUS_DIR"

    # 启动两个持久进程模拟"存活"
    sleep 3600 &
    ALIVE_PID=$!
    sleep 3600 &
    ALIVE_PID2=$!
    echo "    存活 PID: $ALIVE_PID (gateway), $ALIVE_PID2 (dashboard)"

    NOW_TS=$(date +%s)

    # 1) 存活 + deps ok → 正常
    cat > "$STATUS_DIR/default.gateway.${ALIVE_PID}.json" <<EOF
{
  "pid": $ALIVE_PID,
  "agent": "default",
  "role": "gateway",
  "started_at": $NOW_TS,
  "deps": {"msgpack": true},
  "db_root": "$DB_ROOT",
  "plugin_dir": "$MASTER_DIR",
  "version": "1.2.12"
}
EOF
    echo "    ✓ default.gateway.$ALIVE_PID.json  → 预期显示【正常】"

    # 2) 存活 + deps false → 依赖缺失
    cat > "$STATUS_DIR/agent_a.dashboard.${ALIVE_PID2}.json" <<EOF
{
  "pid": $ALIVE_PID2,
  "agent": "agent_a",
  "role": "dashboard",
  "started_at": $NOW_TS,
  "deps": {"msgpack": false},
  "db_root": "$DB_ROOT",
  "plugin_dir": "$MASTER_DIR",
  "version": "1.2.12"
}
EOF
    echo "    ✓ agent_a.dashboard.$ALIVE_PID2.json → 预期显示【依赖缺失】"

    # 3) 死进程 → 已退出
    DEAD_PID=9999999
    cat > "$STATUS_DIR/agent_b.cli.${DEAD_PID}.json" <<EOF
{
  "pid": $DEAD_PID,
  "agent": "agent_b",
  "role": "cli",
  "started_at": $NOW_TS,
  "deps": {"msgpack": true},
  "db_root": "$DB_ROOT",
  "plugin_dir": "$MASTER_DIR",
  "version": "1.2.12"
}
EOF
    echo "    ✓ agent_b.cli.$DEAD_PID.json        → 预期显示【已退出】"
    echo ""
    echo "    ⚠ 脚本退出后，$ALIVE_PID 和 $ALIVE_PID2 会被 kill，"
    echo "       它们的 status 会从【正常/依赖缺失】变成【已退出】——这正是修复目标行为"
fi

# ---------------- 汇总 ----------------
echo ""
echo "============================================"
echo "✅ 测试数据生成完成"
echo "   db_root : $DB_ROOT"
echo "   agents  : $TOTAL_AGENTS 个"
echo "   新增行数: $TOTAL_ROWS"
echo "============================================"
echo ""
echo "下一步："
echo "  1. 打开 booth → 点击顶栏「🔄 刷新」按钮（或等 10s 自动轮询）"
echo "  2. 顶栏「📅 开始」调到 70 天前，点击「🔍 查询」验证历史数据"
echo "  3. 点「🪙 Token 明细」→ 切「按 Agent 汇总」和「详细记录」两个 tab"
echo "  4. 点击右上角状态圆点，验证 status 面板的三态显示"