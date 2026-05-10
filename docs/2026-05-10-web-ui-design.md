# Benchmark Platform Web UI 设计

> 为 benchmark-platform 靶场平台添加 Web 管理界面，复刻 tch 比赛平台交互，兼容 pojun 做题 API。

**目标:** 在现有 FastAPI 服务同端口（默认 8000）上增加 Web 前端，提供完整的比赛平台体验：赛题管理、实例启停、flag 提交、关卡解锁、Scoreboard、提交历史、实例健康状态。

**约束:**
- 单用户本地使用，不做多租户/多队伍隔离
- Web UI 与 API 同端口，`/web/*` 页面路由与 `/api/*` 完全分离
- pojun 继续调用 `/api/*` 接口，行为不变
- 前端零构建步骤，Python 单栈
- UI 风格遵循 RedC GUI 设计规范

---

## 1. 技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| 模板引擎 | Jinja2（FastAPI 内置支持） | Python 单栈 |
| CSS | Tailwind CDN + RedC 设计规范 | 零构建，直接用 class |
| 交互 | HTMX + Alpine.js（CDN） | 局部刷新 + 轻量状态管理 |
| 图标 | Heroicons（SVG 内联） | RedC 规范同款 |

**新增 Python 依赖:**
```toml
"jinja2>=3.1.0",
"aiofiles>=24.0.0",
```

---

## 2. 整体架构

### 路由分层

```
/              → 重定向到 /web/dashboard
/web/*         → 页面路由（返回 HTML）
/web/partials/* → HTMX 局部刷新片段
/api/*         → 现有 API 不变，pojun 继续调用
/docs          → FastAPI 自动文档（保留）
```

### 数据流

```
pojun (AI Agent)                    Web UI (浏览器)
      │                                   │
      │  POST /api/start_challenge        │  点击 [启动] → HTMX POST /api/start_challenge
      │  POST /api/submit                 │  Modal 提交 → HTMX POST /api/submit
      │  GET  /api/challenges             │  页面加载 → Jinja2 渲染（读 manager 状态）
      │                                   │  轮询 → GET /web/partials/*
      │                                   │
      └──────────── 同一个 FastAPI app ────┘
                         │
                    ChallengeManager
                    SubmissionStore
                    (内存状态)
```

核心原则: Web 界面通过 HTMX 调用 `/api/*` 接口，和 pojun 使用完全相同的 API。不为前端单独造数据接口。

### 品牌色适配

沿用 RedC 红色系主题，保持家族感：
- 核心交互（flag 提交、启动靶机）用 `red-600`
- 内容管理页面用 `gray-900` 主按钮
- 状态色不变：emerald=运行中/成功，red=错误，amber=pending

---

## 3. 文件结构

```
benchmark-platform/
├── benchmark_platform/
│   ├── server.py                  # 现有，新增 web_router 挂载
│   ├── web/                       # 新增：Web 界面模块
│   │   ├── __init__.py
│   │   ├── routes.py              # 页面路由 + partials 路由
│   │   ├── context.py             # 模板上下文构建：从 manager/store 读取状态，
│   │   │                          #   组装各页面所需的 dict 供 Jinja2 渲染
│   │   └── templates/
│   │       ├── base.html          # 骨架：侧边栏 + 主内容区 + CDN
│   │       ├── components/
│   │       │   ├── sidebar.html
│   │       │   ├── topbar.html
│   │       │   ├── toast.html
│   │       │   ├── modal_submit.html
│   │       │   ├── modal_confirm.html
│   │       │   ├── challenge_card.html
│   │       │   ├── stats_card.html
│   │       │   └── progress_bar.html
│   │       ├── pages/
│   │       │   ├── dashboard.html
│   │       │   ├── challenges.html
│   │       │   ├── history.html
│   │       │   └── status.html
│   │       └── partials/
│   │           ├── dashboard_stats.html
│   │           ├── challenge_card.html
│   │           ├── history_rows.html
│   │           └── status_table.html
│   └── static/
│       └── css/
│           └── app.css            # 少量自定义样式
```

---

## 4. 页面布局

### 侧边栏（固定 w-56，遵循 RedC 17.x 规范）

```
┌─────────────────┐
│  🏴 Benchmark   │  Logo 区域，from-rose-500 to-red-600 渐变
│    Platform      │
├─────────────────┤
│  ● 仪表盘       │  顶层项，无分组
│                 │
│  赛 题 ──────── │  分组头 text-[10px] uppercase
│    题目列表      │
│    提交记录      │
│                 │
│  系 统 ──────── │
│    实例状态      │
├─────────────────┤
│  ○ 运行中  3/78 │  底部状态摘要
│  ◉ 已解决 12/104│
└─────────────────┘
```

- 选中态：`bg-gray-900 text-white`
- 默认：`text-gray-600 hover:bg-gray-50`

### 页面顶栏

```html
<div class="px-6 py-4 border-b border-gray-100 bg-white">
  <h1 class="text-lg font-semibold text-gray-900">页面标题</h1>
  <p class="text-[12px] text-gray-500 mt-0.5">页面描述</p>
</div>
```

---

## 5. 仪表盘页（Dashboard）

路由: `/web/dashboard`

### 统计卡片（顶部 4 格 grid-cols-4）

| 卡片 | 主数字 | 辅助信息 |
|------|--------|---------|
| 总题目 | 78 | 104 flags |
| 已解决 | 12（emerald-600） | 15.4% |
| 总得分 | 2400/5200 | 进度条 |
| 运行中实例 | 3（amber-600） | / 78 |

### 关卡进度卡片

- 已解锁关卡：进度条 `bg-emerald-500`（已完成）+ `bg-gray-200`（未完成）
- 未解锁关卡：`opacity-40` + 锁图标 + "需通过 Level N 解锁"

### 最近提交卡片

最新 10 条提交记录时间线：
- 正确：`bg-emerald-50 text-emerald-600` Badge
- 错误：`bg-red-50 text-red-600` Badge

### 难度分布卡片

Easy/Medium/Hard 各难度的完成率水平条。

### 自动刷新

```html
<div hx-get="/web/partials/dashboard_stats" hx-trigger="every 5s" hx-swap="innerHTML">
```

---

## 6. 题目列表页（Challenges）

路由: `/web/challenges`

### 布局

题目按关卡（Level）分组展示，每组内为卡片网格（grid-cols-3）。

### 题目卡片

```html
<div class="bg-white rounded-xl border border-gray-100 p-5 flex flex-col gap-3">
  <!-- 头部：benchmark_id + 标题 + 难度Badge -->
  <!-- 中部：描述 + flag进度 + 实例状态 + 分值 -->
  <!-- 多flag进度条（仅多flag题） -->
  <!-- 底部：操作按钮 -->
</div>
```

### 难度 Badge

| 难度 | 样式 |
|------|------|
| Easy | `bg-emerald-50 text-emerald-600` |
| Medium | `bg-amber-50 text-amber-600` |
| Hard | `bg-red-50 text-red-600` |

### 实例状态指示

| 状态 | 样式 |
|------|------|
| stopped | `text-gray-400` ○ stopped |
| running | `text-emerald-600` ● running + entrypoint 链接 |
| pending | `text-amber-500` + spinner ◌ starting... |

### 操作按钮

| 操作 | 条件 | 样式 |
|------|------|------|
| 启动 | stopped 且未全解 | `bg-gray-900 text-white` |
| 停止 | running | `border border-gray-300 text-gray-700` |
| 提交 Flag | running | `bg-red-600 text-white` |
| 查看提示 | running 且未查看 | `text-gray-500 hover:text-gray-700` |
| 查看进度 | 多 flag 题 | 文字链接 |
| 已完成 | solved | `opacity-50` + 勾号 |

### Flag 提交 Modal

遵循 RedC 12.x Modal 规范。输入框 + 提交按钮，HTMX POST 到 `/api/submit`，Toast 反馈结果。

### 关卡解锁（Level Gate）

- 已通过关卡：正常显示，标题右侧 `✓ 已通过` Badge
- 当前关卡：正常显示，可操作
- 未解锁关卡：`opacity-40` 遮罩 + "需通过 Level N 解锁"
- `--no-level-gate` 启动时所有关卡可见可操作

### 筛选与搜索

顶部栏：下拉筛选（全部/未解决/已解决/运行中）+ 搜索框。Alpine.js 客户端过滤。

---

## 7. 提交记录页（History）

路由: `/web/history`

### 数据存储

新增 `SubmissionStore` 类，内存存储 + JSONL 持久备份：

```python
@dataclass
class SubmissionRecord:
    timestamp: str
    challenge_code: str
    benchmark_id: str
    challenge_name: str
    flag_id: str | None
    flag_value: str          # 脱敏显示
    correct: bool
    points: int
```

在 `/api/submit` 处理逻辑末尾插入 `submission_store.add(record)`。

### 表格（RedC 8.x 规范）

| 列 | 内容 |
|------|------|
| 时间 | `font-mono text-[13px]` |
| 题目 | 名称 + code |
| Flag ID | flag_id + route（多 flag 题） |
| 结果 | Badge: ✓正确 / ✗错误 / ↻重复 |
| 得分 | 正确 `text-emerald-600` +N / 错误 `text-gray-400` — |

### 自动刷新

```html
<tbody hx-get="/web/partials/history_rows" hx-trigger="every 3s" hx-swap="innerHTML">
```

---

## 8. 实例状态页（Status）

路由: `/web/status`

### 表格

| 列 | 内容 |
|------|------|
| 题目 | 名称 + code |
| Benchmark ID | `font-mono text-purple-600` |
| 端口映射 | 可点击链接 `localhost:port → container_port`，新标签页打开靶机 |
| 状态 | Badge |
| 操作 | 启动/停止/访问 |

### 显示策略

- 运行中的实例显示在顶部
- 已停止的折叠在可展开区域内

### "全部停止" 按钮

危险操作（`bg-red-500 text-white`），点击弹出确认 Modal（amber 警告图标）。

### Docker 资源概览

底部卡片：容器总数、运行中、已停止。

### 自动刷新

```html
<div hx-get="/web/partials/status_table" hx-trigger="every 5s" hx-swap="innerHTML">
```

---

## 9. 后端改动

### server.py

- 挂载 StaticFiles 和 web_router
- 根路由 `/` 重定向到 `/web/dashboard`
- `/api/submit` 末尾追加 `submission_store.add(record)`

### ChallengeManager 新增

```python
def get_current_level(self) -> int:
    """基于已解决题目计算当前解锁到哪一关。"""

def is_level_unlocked(self, level: int) -> bool:
    """判断指定关卡是否解锁。no_level_gate 时始终返回 True。"""
```

### HTMX Partials 路由

```
GET /web/partials/dashboard_stats
GET /web/partials/history_rows
GET /web/partials/status_table
GET /web/partials/challenge_card?code={code}
```

返回 HTML 片段，不继承 base.html。

---

## 10. 交互流总览

### 启动靶机

1. 用户点击 [启动]
2. HTMX POST `/api/start_challenge`
3. 成功 → Toast "靶机启动成功" + 卡片刷新（状态变 running，显示 entrypoint 链接）
4. 失败 → Toast 错误信息

### 提交 Flag

1. 用户点击 [提交 Flag] → 弹出 Modal
2. 输入 flag 值，点击提交
3. HTMX POST `/api/submit`
4. 正确 → Toast "恭喜！答案正确" + 卡片刷新（进度更新）
5. 错误 → Toast "答案错误"
6. 同时 SubmissionStore 记录提交，History 页自动刷新可见

### pojun 做题期间

1. pojun 调用 `/api/start_challenge` 启动靶机
2. pojun 调用 `/api/submit` 提交 flag
3. Web UI Dashboard 每 5s 轮询刷新 → 统计数据实时更新
4. Web UI History 每 3s 轮询 → 提交记录实时追加
5. Web UI Status 每 5s 轮询 → 实例状态实时更新
6. 用户可通过 Status 页端口链接直接访问靶机

---

## 11. 实施顺序

1. **基础骨架** — base.html、侧边栏、路由挂载、静态资源
2. **Dashboard 页** — 统计卡片、关卡进度、难度分布
3. **Challenges 页** — 题目卡片、启停操作、flag 提交 Modal
4. **SubmissionStore** — 提交记录存储 + API 集成
5. **History 页** — 提交记录表格
6. **Status 页** — 实例状态表格、端口链接、全部停止
7. **Level Gate** — 关卡解锁逻辑
8. **HTMX 轮询** — 所有 partials 自动刷新
9. **端到端测试** — 启动平台 + Web UI 验证全流程
