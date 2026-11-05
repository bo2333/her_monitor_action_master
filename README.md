# monitor_action_master

观察 Hermes 运行时事件，按 Agent 分文件持久化到 SQLite，可选 TCP 推送。零 Token 开销。

## 依赖

插件依赖在 `plugin.yaml` 的 `python_dependencies` 中声明。由 Hermes PM 在
`hermes plugins enable monitor_action_master` 时自动安装。

若 PM 不可用，可手动安装：

    $PY -m pip install "msgpack>=1.0"

`$PY` 为 Hermes 实际使用的解释器（`sys.executable`）。

## 配置

`config/master_config.json`：

| 字段 | 说明 |
|------|------|
| `enabled` | 插件总开关 |
| `db_root` | SQLite 根目录，实际文件为 `{db_root}/{agent}.db` |
| `remote.enabled` | 是否启用 TCP 推送 |
| `remote.host` / `remote.port` | TCP 目标地址 |

修改后需重启 Hermes 或调用 `get_config().reload()`。

## 数据

每 Agent 一个 SQLite 文件，表 `events` 存事件明细：

| 列 | 说明 |
|----|------|
| `ts` | Unix 时间戳 |
| `user` | Agent 名 |
| `action` | 事件动作 |
| `flow` | 0=请求侧，1=响应侧 |
| `conn` | 事件内容（截断至 15KB） |
| `level` | 0 调试 / 1 常规 / 2 Token / 3 警告 / 4 错误 |
| `input_tokens` / `output_tokens` / `total_tokens` | Token 用量 |

写入为异步批量（0.5s 一批，最多 500 条），不阻塞主流程。

## 事件来源

注册 27 个纯 observer hook，覆盖 LLM、API、工具、会话、审批、子代理、Kanban 等。
不注册任何 `transform_*` hook，不改变运行时行为。

## 日志

- 插件自身使用 `logging.getLogger("monitor_action_master")`，由 Hermes 集中管理。
- 依赖缺失信息写入 `logs/deps.log`，包含可执行的修复命令。

## 从 v1.0 迁移

- 删除 `install_deps.sh`、`billing/`、`log_utils.py`、`config_manager.py`、`core/`。
- 根目录 `master_config.json` 迁移到 `config/master_config.json`。
- `daily_stats` 表和费用计算交给 Hermes，插件不再自算。
- `transform_*` hook 已移除（与“旁路监听”定位冲突）。


###
monitor_action_master/
├── plugin.yaml                    # 元信息 + 依赖声明
├── __init__.py                    # 入口：路径兜底 → 依赖检查 → 注册 hooks
├── README.md
│
├── config/                        # 配置（代码与配置分离）
│   ├── __init__.py
│   ├── defaults.py                # 默认配置常量
│   ├── loader.py                  # 读写 master_config.json
│   └── master_config.json         # 用户配置文件
│
├── deps/                          # 依赖检查（只检查，不安装）
│   ├── __init__.py
│   └── checker.py
│
├── context/                       # Agent 上下文
│   ├── __init__.py
│   └── agent_ctx.py               # thread-local + contextvars
│
├── log/                           # 日志（交给 Hermes 集中管理）
│   ├── __init__.py
│   └── logger.py
│
├── storage/                       # SQLite 持久化
│   ├── __init__.py
│   ├── schema.sql                 # events 表 DDL
│   ├── db.py                      # 连接管理
│   └── writer.py                  # 异步批量写入
│
├── events/                        # 事件格式化
│   ├── __init__.py
│   └── formatter.py
│
├── hooks/                         # 27 个 observer hook
│   ├── __init__.py
│   ├── handlers.py                # 处理函数
│   └── registry.py                # hook 列表 + 注册闭包
│
└── sinks/                         # 外部推送（可选）
    ├── __init__.py
    └── tcp_client.py              # TCP + msgpack