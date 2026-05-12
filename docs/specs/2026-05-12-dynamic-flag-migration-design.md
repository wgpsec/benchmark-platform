# 靶场动态 Flag 改造设计

## 目标

让所有靶场在运行时从环境变量获取 flag，不在 Docker 构建时烘焙进镜像，从而：
- 每次启动实例获得唯一动态 flag
- 兼容预热缓存（镜像不含 flag，可安全复用）
- 保持 `cat /flag.txt` 的传统攻击路径不变

## 核心规范

### 1. Dockerfile

- **禁止** `ARG FLAG` 和 `RUN echo $FLAG > /flag.txt` 写法
- 使用 entrypoint wrapper 在容器启动时写入 flag

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com flask

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "app.py"]
```

### 2. entrypoint.sh

通用模板，放在每个服务的 build context 根目录：

```bash
#!/bin/bash
echo -n "${FLAG:-FLAG{default_flag}}" > /flag.txt
exec "$@"
```

对于需要在 SQL 中插入 flag 的数据库容器：

```bash
#!/bin/bash
echo -n "$FLAG" > /flag.txt
if [ -f /docker-entrypoint-initdb.d/init.sql.tpl ]; then
  sed "s|__FLAG__|$FLAG|g" /docker-entrypoint-initdb.d/init.sql.tpl > /docker-entrypoint-initdb.d/init.sql
fi
exec "$@"
```

### 3. docker-compose.yml

```yaml
services:
  web:
    build:
      context: ./src
      # 不再有 args: FLAG
    environment:
      - FLAG=${FLAG}
    ports:
      - "80:80"
```

多服务场景中，只有需要 flag 的服务传递 `FLAG` 环境变量。

### 4. 应用代码

- 从环境变量或 `/flag.txt` 读取 flag
- 不允许硬编码 flag 字符串

```python
import os
FLAG = os.environ.get("FLAG", open("/flag.txt").read().strip())
```

```javascript
const FLAG = process.env.FLAG || require('fs').readFileSync('/flag.txt', 'utf8').trim();
```

### 5. .env 文件

靶场源码中的 `.env` 保留静态默认值（用于本地开发/测试）：

```
FLAG="FLAG{default_local_dev_flag}"
```

平台启动时会将此值替换为动态生成的 `flag{uuid}` 格式。

## SQL Seed 场景

对于 flag 存在数据库中的靶场（如 `init.sql` 插入 flag 值）：

**方案：模板替换**

1. 将 `init.sql` 重命名为 `init.sql.tpl`，flag 位置用占位符 `__FLAG__`
2. 自定义 entrypoint（或 Dockerfile 中 RUN 脚本）在容器启动时 sed 替换
3. 对于 PostgreSQL/MySQL 官方镜像，利用其 `/docker-entrypoint-initdb.d/` 机制

示例 `init.sql.tpl`：
```sql
INSERT INTO secrets (id, value) VALUES (1, '__FLAG__');
```

数据库服务 docker-compose 配置：
```yaml
  db:
    image: postgres:15-alpine
    environment:
      - FLAG=${FLAG}
    volumes:
      - ./db/init.sql.tpl:/init.sql.tpl:ro
      - ./db/entrypoint-db.sh:/docker-entrypoint-initdb.d/00-flag.sh:ro
```

`entrypoint-db.sh`：
```bash
#!/bin/bash
sed "s|__FLAG__|$FLAG|g" /init.sql.tpl > /docker-entrypoint-initdb.d/01-data.sql
```

## 平台侧

### _inject_dynamic_flags 保留为 fallback

- 正常流程：平台生成动态 flag → 写入 `.env` → docker-compose 通过 `${FLAG}` 传给容器 → entrypoint 写 `/flag.txt`
- Fallback：对于未改造的靶场或用户导入的非规范靶场，继续做源码全文替换

### 预热缓存兼容

改造后 Dockerfile 不含 flag 值，预热镜像可以安全复用。运行时 flag 通过 environment 注入，与镜像内容完全解耦。

## 需要改造的靶场清单

以下 21 个靶场源码中硬编码 flag 且不读取环境变量，需要优先改造：

```
argus/APEX-002-25    argus/APEX-003-25    argus/APEX-005-25
argus/APEX-011-25    argus/APEX-017-25    argus/APEX-023-25
argus/APEX-027-25    argus/APEX-029-25    argus/APEX-033-25
argus/APEX-035-25    argus/APEX-037-25    argus/APEX-046-25
argus/APEX-047-25    argus/APEX-048-25    argus/APEX-051-25
argus/APEX-052-25    argus/APEX-053-25    argus/APEX-057-25
argus/APEX-058-25    argus/APEX-059-25    custom/CMD-RCE-01
```

另外，所有使用 `build.args: FLAG` 的靶场（约 100+ 个）也需要移除 `ARG FLAG`，改为纯 environment 注入 + entrypoint 写文件模式。

## 执行方式

1. 更新 `docs/challenge-spec.md` — 加入动态 flag 规范章节
2. 更新 `.claude/skills/create-challenge.md` — 生成的靶场遵循新规范
3. 用 AI 逐个改造现有靶场

## 成功标准

- 所有靶场 `docker compose build` 后镜像中不含 flag 值
- 启动实例后 `docker exec <container> cat /flag.txt` 输出的是平台生成的动态 flag
- 预热镜像可以安全复用，启动速度不受影响
- 做题者的利用路径（如 `cat /flag.txt`、SQL 查询 flag 字段）保持不变
