# Compose 操作可观测性增强（AD 系列靶场）

## 目标

为管理员提供 AD 系列靶场（Windows ISO，`requires_windows_iso == True`）docker compose 长时间运行操作（15-30 分钟启动）的实时日志可视化，在 Web Dashboard 的 Challenge Card 上直接展示 compose 输出流。

其他靶场行为完全不变。

## 背景

当前 `_compose()` 使用 `subprocess.run(capture_output=True)` 一次性阻塞执行。compose 期间没有任何中间输出，状态模型只有 `stopped` / `running`，前端 fetch `/api/start_challenge` 会 hold 住直到 compose 完成（AD 靶场长达 30 分钟）。管理员无法判断 compose 在做什么（拉镜像？构建？卡住了？）。

PrebuildManager 中已有一套 `Popen` + `log_lines` + 轮询的模式可以复用。

## 范围

仅对 `requires_windows_iso == True` 的 AD 系列靶场启用以下增强：

- 后端：线程化异步启动，compose 日志积累
- 前端：日志面板、中间态动画、fire-and-forget 启动

其他靶场保持现有同步阻塞启动 + 转圈等待的行为。

判定依据：`Challenge.requires_windows_iso` 字段（已有，由 `_detect_requires_windows_iso()` 检测 compose 文件中的 dockur 镜像）。

## 设计

### 1. `_compose()` 改造 — Popen 流式读取

**文件：** `benchmark_platform/utils/challenge.py`

将 `_compose()` 从 `subprocess.run()` 改为 `subprocess.Popen()`（对所有靶场生效，调用者透明）：

- `Popen(cmd, cwd=path, stdout=PIPE, stderr=STDOUT, text=True)` 合并 stdout/stderr
- 逐行 `readline()`，每行追加到 `self._instance_logs[benchmark_id]: list[str]`
- 日志列表上限 500 行，超出时 `del logs[:len(logs)-500]`
- 不加锁，与 PrebuildManager 模式一致（GIL 保证 `list.append` 原子性）
- compose 启动前清空该 benchmark_id 的旧日志
- 超时处理：手动计时，超时时 `proc.terminate()`
- 返回值/异常行为不变，对调用者透明

### 2. 状态模型增加中间态

**文件：** `benchmark_platform/utils/challenge.py`

- 启动流程：`stopped` → `starting` → `running`（成功）或 `stopped`（失败）
- 停止流程：`running` → `stopping` → `stopped`
- `_instance_status` dict 中直接使用这些字符串值
- `start_challenge_instance()` 在调用 `_compose()` 前设置 `starting`
- `stop_challenge_instance()` 在调用 `_compose()` 前设置 `stopping`

### 3. AD 靶场异步启动

**文件：** `benchmark_platform/utils/challenge.py`

在 `start_challenge_instance()` 中，当 `challenge.requires_windows_iso == True` 时：

- 完成前置检查（ISO 路径验证、目录准备、ISO 注入）后，开 `threading.Thread` 执行 compose
- 立即返回，不等待 compose 完成
- 线程内 compose 成功后设置状态为 `running`，失败则回退为 `stopped`

非 Windows ISO 靶场保持原有同步阻塞行为不变。

对应 server.py 中 `/api/start_challenge`：当后端立即返回时，HTTP 响应变为 202 Accepted（可通过返回值区分同步/异步完成）。

### 4. 日志 API 端点

**文件：** `benchmark_platform/server.py`

新增端点：

```
GET /api/instance_logs?benchmark_id=xxx&offset=0
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
- 日志超 500 行触发截断时，前端发现 `total < offset` 则重置为 0

该端点走 Web Dashboard 路径，不需要 Agent-Token 认证。扁平 query param 风格，与项目现有 API 约定一致。

### 5. 现有 API 行为

- `POST /api/start_challenge`：非 Windows ISO 靶场保持同步阻塞，Agent / MCP 调用不受影响；Windows ISO 靶场返回 202 Accepted
- `POST /api/stop_challenge`：所有靶场保持同步阻塞（stop 通常很快）
- `GET /api/instance_statuses`：将 `starting` / `stopping` 中间态传递出去

### 6. 前端 Challenge Card UI

**文件：** `benchmark_platform/web/templates/components/challenge_card.html`

以下改动仅对 `requires_windows_iso` 的 card 生效：

**状态显示增强：**

- `starting`：绿色脉冲圆点 + "启动中…"
- `stopping`：灰色脉冲圆点 + "停止中…"
- `starting` / `stopping` 时启动和停止按钮均禁用

**日志面板：**

- `starting` 或 `stopping` 状态时，card 底部展开深色背景日志面板
- 等宽字体，自动滚到底部
- 前端每 2 秒轮询 `GET /api/instance_logs?benchmark_id=xxx&offset=N`，增量追加新行
- 状态变为 `running` 后停止轮询，面板自动折叠
- 状态变为 `stopped`（从 `starting` 回落，即启动失败）：最后拉一次日志，面板保留展示错误输出，不自动折叠，用户手动关闭

**启动按钮行为（仅 AD 靶场）：**

- 点击后 `fetch` 发出请求，拿到 202 响应后 card 进入 `starting` 状态，开始轮询日志
- card 状态由 `/api/instance_statuses` 轮询驱动

**其他靶场：**

- 保持现有行为：点击 start → fetch 阻塞等待 → 响应后 partial card 刷新

### 7. 不做的事

- 不引入 SSE / WebSocket — 轮询足够，与项目现有模式一致
- 不引入 `error` 状态 — 失败回到 `stopped`，错误信息在日志面板中展示
- 不改 Agent API 同步行为（非 Windows ISO 靶场）
- 日志不持久化 — 纯内存，服务重启后丢失，下次启动时清空
- 不改 MCP 接口
- 不改非 AD 系列靶场的任何行为

## 影响范围

| 文件 | 改动 |
|------|------|
| `benchmark_platform/utils/challenge.py` | `_compose()` 改 Popen（所有靶场），增加 `_instance_logs` dict，状态中间态，AD 靶场线程化启动 |
| `benchmark_platform/server.py` | 新增 `/api/instance_logs` 端点，`/api/start_challenge` 对 AD 靶场返回 202，`instance_statuses` 传递中间态 |
| `benchmark_platform/web/templates/components/challenge_card.html` | AD 靶场：日志面板 UI、状态显示增强、启动按钮异步化、按钮禁用态 |
