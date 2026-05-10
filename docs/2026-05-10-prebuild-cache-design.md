# 镜像预缓存页面设计

> 解决首次启动题目时 docker pull/build 耗时过长的问题，提供 Web UI 让用户提前预热镜像。

## 页面入口

侧边栏「系统」分组下新增「镜像预热」导航项，路由 `/web/prebuild`。

## 页面布局

**顶部操作栏：**
- 统计：已缓存 X / 总共 Y 个题目
- 「开始预构建」按钮 + 并发数选择器（1/2/3，默认 1）
- 预构建运行时显示「停止」按钮

**主体：题目列表表格，每行：**
- 题目 ID + 名称
- 状态标签：`未缓存` / `构建中`（spinner）/ `已缓存` / `失败`
- 点击行可展开实时 build 日志（自动滚动跟随）

## 后端设计

### 判断缓存状态

对每个 challenge 执行 `docker compose config --images` 获取镜像列表，再用 `docker image inspect` 检测是否已存在本地。全部镜像都存在 = 已缓存。

### API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/prebuild/start` | POST | 启动后台构建任务，body: `{concurrency: 1}` |
| `/api/prebuild/stop` | POST | 取消剩余未开始的任务 |
| `/api/prebuild/status` | GET | 返回所有题目当前状态 + 日志 |

### 预构建任务

- 后端用 `ThreadPoolExecutor(max_workers=concurrency)` 执行 `docker compose build`
- 每个任务的 stdout/stderr 流式写入内存 buffer（per challenge）
- 前端每 2s 轮询 `/api/prebuild/status` 获取增量
- 已缓存的题目自动跳过

### 状态模型

```python
class PrebuildStatus:
    challenge_code: str
    benchmark_id: str
    name: str
    status: str  # "pending" | "building" | "cached" | "failed"
    log_lines: list[str]
```

## 数据流

```
用户点击「开始预构建」
  → POST /api/prebuild/start {concurrency: 1}
  → 后端创建 PrebuildManager，线程池逐个 build
  → 前端每 2s GET /api/prebuild/status
  → 返回 [{code, benchmark_id, name, status, log_lines}, ...]
  → 前端更新每行状态 + 展开的日志区域
```

## 不做的事

- 不做 WebSocket/SSE（轮询够用，实现简单）
- 不做持久化（重启 server 状态清零，缓存已在 Docker 里）
- 不做单题重试按钮（失败后重新点「开始」会跳过已缓存的）
