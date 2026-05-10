#!/bin/bash
# 在 Mac 上运行：对所有 challenge 做 docker compose build，然后 save 镜像
# 用法：bash scripts/build_and_save_challenges.sh
set -e

CHALLENGES_DIR="$(cd "$(dirname "$0")/.." && pwd)/challenges"
SAVE_DIR="$(dirname "$0")/images/challenges"
mkdir -p "$SAVE_DIR"

# 收集所有需要构建的 challenge 目录
DIRS=$(find "$CHALLENGES_DIR" -maxdepth 1 -mindepth 1 -type d ! -name ".*" | sort)

TOTAL=$(echo "$DIRS" | wc -l | tr -d ' ')
COUNT=0
FAILED=()

for dir in $DIRS; do
  name=$(basename "$dir")
  COUNT=$((COUNT + 1))

  if [ ! -f "$dir/docker-compose.yml" ]; then
    echo "[$COUNT/$TOTAL] ⏭ $name — no docker-compose.yml, skipping"
    continue
  fi

  tar_file="$SAVE_DIR/${name}.tar"
  if [ -f "$tar_file" ]; then
    echo "[$COUNT/$TOTAL] ✓ $name — already built, skipping"
    continue
  fi

  echo "[$COUNT/$TOTAL] → $name — building..."

  # 读取 .env 里的 FLAG 变量供 build args 使用
  FLAG_VAL=""
  if [ -f "$dir/.env" ]; then
    FLAG_VAL=$(grep -m1 "^FLAG=" "$dir/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
    if [ -z "$FLAG_VAL" ]; then
      FLAG_VAL=$(grep -m1 "^FLAG1=" "$dir/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
    fi
  fi

  # Build
  if FLAG="$FLAG_VAL" docker compose -f "$dir/docker-compose.yml" build 2>&1; then
    # 收集该 compose 文件构建的所有镜像名
    IMAGES=$(docker compose -f "$dir/docker-compose.yml" config --images 2>/dev/null)
    if [ -n "$IMAGES" ]; then
      docker save $IMAGES -o "$tar_file"
      echo "  ✓ saved to ${name}.tar ($(du -sh "$tar_file" | cut -f1))"
      # 清理构建的镜像释放空间
      docker rmi $IMAGES >/dev/null 2>&1 || true
    else
      echo "  ✗ no images found after build"
      FAILED+=("$name")
    fi
  else
    echo "  ✗ build failed"
    FAILED+=("$name")
  fi
done

echo ""
echo "===== 完成 ====="
echo "成功: $((COUNT - ${#FAILED[@]}))/$TOTAL"
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "失败: ${FAILED[*]}"
fi
echo "镜像目录: $SAVE_DIR"
du -sh "$SAVE_DIR"
