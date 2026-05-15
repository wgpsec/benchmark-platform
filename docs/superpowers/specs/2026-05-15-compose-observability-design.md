# Compose 操作可观测性增强

## 目标

为管理员提供 docker compose 长时间运行操作（特别是 AD/Windows ISO 靶场 15-30 分钟启动）的实时日志可视化，在 Web Dashboard 的 Challenge Card 上直接展示 compose 输出流。

## 背景

当前 `_compose()` 使用 `subprocess.run(capture_output=True)` 一次性阻塞执行。compose 期间没有任何中间输出，状态模型只有 `stopped` / `running`，前端只有一个 CSS spinner 转圈。对于 AD 靶场（Windows ISO）启动需要 15-30 分钟的场景，管理员无法判断 compose 在做什么（拉镜像？构建？卡住了？）。

PrebuildManager 中已有一套 `Popen` + `log_lines` + 轮询的模式可以复用。

## 设计

### 1. `_compose()` 改造 — Popen 流式读取

**文件：** `benchmark_platform/utils/challenge.py`

将 `_compose()` 从 `subprocess.run()` 改为 `subprocess.Popen()`：

- `Popen(cmd, cwd=path, stdout=PIPE, stderr=STDOUT, text=True)` 合并 stdout/stderr
- 逐行 `readline()`，每行追加到 `self._instance_logs[benchmark_id]: list[str]`
- 日志列表上限 500 行，超出时丢弃最早的行
- compose 启动前清空该 benchmark_id 的旧日志
- 超时处理：用 `threading.Timer` 或手动计时，超时时 `proc.terminate()`
- 返回值/异常行为不变，对调用者透明

### 2. 状态模型增加中间态

**文件：** `benchmark_platform/utils/challenge.py`

- 启动流程：`stopped` → `starting` → `running`（成功）或 `stopped`（失败）
- 停止流程：`running` → `stopping` → `stopped`
- `_instance_status` dict 中直接使用这些字符串值
- `start_challenge_instance()` 在调用 `_compose()` 前设置 `starting`
- `stop_challenge_instance()` 在调用 `_compose()` 前设置 `stopping`

### 3. 日志 API 端点

**文件：** `benchmark_platform/server.py`

新增端点：

```
GET /api/instance/{benchmark_id}/logs?offset=0
```

响应：

```json
{
  "status": "starting",
  "logs": ["Step 1/5 : FROM python:3.12", "Pulling image..."],
  "total": 150
}
```

- `offset` 参数：从第几行开始返回，用于增量拉取
- `status`：该实例当前状态（`starting` / `running` / `stopping` / `stopped`）
- `logs`：从 offset 开始的日志行
- `total`：日志总行数（前端用于下次请求的 offset）
- 无日志时返回空列表

该端点走 Web Dashboard 路径，不需要 Agent-Token 认证。

### 4. 现有 API 行为不变

- `POST /api/start_challenge`：保持同步阻塞，Agent / MCP 调用不受影响
- `GET /api/instance_statuses`：将 `starting` / `stopping` 中间态传递出去

### 5. 前端 Challenge Card UI

**文件：** `benchmark_platform/web/templates/components/challenge_card.html`

状态显示增强：

- `starting`：绿色脉冲圆点 + "启动中…"
- `stopping`：灰色脉冲圆点 + "停止中…"
- 其他状态不变

日志面板：

- `starting` 或 `stopping` 状态时，card 底部展开深色背景日志面板
- 等宽字体，自动滚到底部
- 前端每 2 秒轮询 `GET /api/instance/{benchmark_id}/logs?offset=N`，增量追加新行
- 状态变为 `running` 或 `stopped` 后停止轮询，面板保留显示最终日志

启动按钮行为：

- 点击后 `fetch` 发出请求，**不等待响应**
- card 立即进入 `starting` 状态，开始轮询日志
- fetch 最终的响应到达后忽略（card 状态由 `/api/instance_statuses` 轮询驱动）

### 6. 不做的事

- 不引入 SSE / WebSocket — 轮询足够，与项目现有模式一致
- 不改 Agent API 同步行为 — TCH 兼容性不受影响
- 日志不持久化 — 纯内存，服务重启后丢失
- 不改 MCP 接口

## 影响范围

| 文件 | 改动 |
|------|------|
| `benchmark_platform/utils/challenge.py` | `_compose()` 改 Popen，增加 `_instance_logs` dict，状态中间态 |
| `benchmark_platform/server.py` | 新增日志 API，`instance_statuses` 传递中间态 |
| `benchmark_platform/web/templates/components/challenge_card.html` | 日志面板 UI，状态显示增强，启动按钮异步化 |
