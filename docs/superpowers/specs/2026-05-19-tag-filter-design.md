# Tag Filter Design

## Goal

为题目列表、镜像预热、靶场管理三个页面添加按 tags 分类筛选功能。标签数据已存在于 benchmark.json 中，只需暴露到前端并添加筛选 UI。

## Constraints

- 纯前端过滤（客户端 JS），不增加新的后端 API
- 标签栏为页面顶部独立一行，与现有筛选逻辑叠加
- 多选标签时使用 AND（交集）逻辑
- 不改变现有数据模型或 benchmark.json 格式

## Data Flow

### 当前状态

- `benchmark.json` 中 `tags: list[str]` 是必填字段，已有丰富数据
- 运行时通过 `challenge.get_benchmark().tags` 可获取
- `context.py` 的 `_challenge_to_card()` 未传递 tags 到前端
- 前端模板无任何 tag 相关逻辑

### 改动

1. **context.py** — `_challenge_to_card()` 返回字典中添加 `"tags": bm.tags`
2. **challenges.html** — 从 `level_groups` 数据中收集所有唯一标签，渲染标签栏，JS 过滤逻辑
3. **prebuild.html** — prebuild status API 返回数据中补充 tags 字段，前端渲染标签栏并过滤表格行
4. **store.html** — store manifest 已包含 tags 字段（来自 benchmark.json），前端渲染标签栏并过滤列表

## UI Design

### 标签栏

- 位置：页面顶部独立一行（在标题/统计下方，在内容区上方）
- 布局：横向排列 pill 按钮，溢出时水平滚动（`overflow-x-auto`）
- 样式：
  - 未选中：`bg-gray-100 text-gray-600 border border-gray-200`
  - 选中：`bg-gray-900 text-white`
  - hover：`hover:bg-gray-200`（未选中时）
- 尺寸：`text-[11px] px-2.5 py-1 rounded-full`（与现有 UI 风格一致）
- 标签排序：按出现频次降序（出现在最多题目中的标签排前面）
- 标签名展示：原始值（小写英文，如 `rce`、`ognl`、`java`）
- 右侧有"清除筛选"按钮，仅在有标签被选中时显示

### 过滤逻辑

```
已选标签集合 = {tag1, tag2, tag3}
题目可见条件 = 题目.tags ⊇ 已选标签集合（题目的标签集包含所有已选标签）
```

即 AND 交集：选了 `rce` + `java`，只显示同时带有这两个标签的题目。

### 与现有筛选的叠加

- **题目列表页**：标签过滤 + 状态过滤（全部/未解决/已解决/运行中）+ 搜索框，三者叠加
- **镜像预热页**：标签过滤 + 现有搜索，两者叠加
- **靶场管理页**：标签过滤 + 分类分组 + 搜索，三者叠加

## Per-Page Details

### 题目列表页 (challenges.html)

数据来源：Jinja 模板渲染时 `level_groups` 中的每个 card 已有 `tags` 字段。

实现：
- 在 Jinja 中收集所有 card 的 tags 并去重排序
- 渲染标签栏 HTML
- JS：遍历所有 `.challenge-card`，读取 `data-tags` 属性（JSON 数组字符串），与已选标签做 AND 匹配
- 与现有 `filterCards()` 函数整合

### 镜像预热页 (prebuild.html)

数据来源：`/api/prebuild/status` API 返回每个 challenge 的状态信息。

实现：
- API 响应中为每个 challenge 补充 `tags` 字段（从已加载的 challenge metadata 获取）
- 前端 JS 收集所有 tags 渲染标签栏
- 过滤表格行时读取行数据中的 tags

### 靶场管理页 (store.html)

数据来源：远程 manifest.json 已包含 `tags` 字段；本地扫描的 challenge 也有。

实现：
- `ChallengeStore.get_local_challenges()` 中读取 benchmark.json 的 tags 字段
- 前端 Alpine.js 数据中已有 tags（从 manifest/local 合并）
- 渲染标签栏，过滤 `challenges` 数组

## Out of Scope

- 标签管理（增删改）
- 标签颜色分类
- 后端 API 层面的过滤参数
- URL 持久化筛选状态（刷新页面重置）
