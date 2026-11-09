# test/

开发期测试脚本目录，**不随插件运行时加载**，对生产环境无影响。

## seed_monitor_data.sh

往 `db_root` 下的 `{agent}.db` 写入测试数据，覆盖所有 action、level、flow、
时间桶，用于验证 booth 的日志渲染、Token 统计、状态面板三态显示。

### 前置依赖

```bash
apt-get install -y sqlite3        # Debian/Ubuntu
# 或 yum install -y sqlite        # CentOS/RHEL



### 快速开始
```
chmod +x test/seed_monitor_data.sh

# 最简：3 个 agent，每种 action 4 条
./test/seed_monitor_data.sh

# 先清空再写 default，每种 action 2 条
./test/seed_monitor_data.sh -c -a default -n 2

# 同时测试状态面板三态（正常 / 依赖缺失 / 已退出）
./test/seed_monitor_data.sh -c -s
```