#!/bin/bash
# 在 VM 上运行：预构建所有 challenge 镜像
# 用法：bash /opt/benchmark-platform/scripts/prebuild_on_vm.sh
set -e

CHALLENGES_DIR="/opt/benchmark-platform/challenges"
DIRS=$(find "$CHALLENGES_DIR" -maxdepth 1 -mindepth 1 -type d ! -name ".*" | sort)
TOTAL=$(echo "$DIRS" | wc -l | tr -d ' ')
COUNT=0
FAILED=()
SKIPPED=0

echo "===== 预构建 Challenge 镜像 ====="
echo "共 $TOTAL 个 challenge"
echo ""

for dir in $DIRS; do
  name=$(basename "$dir")
  COUNT=$((COUNT + 1))

  if [ ! -f "$dir/docker-compose.yml" ]; then
    echo "[$COUNT/$TOTAL] ⏭ $name — 无 docker-compose.yml，跳过"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # 检查镜像是否已存在
  IMAGES=$(FLAG=x docker compose -f "$dir/docker-compose.yml" config --images 2>/dev/null)
  ALL_EXIST=true
  for img in $IMAGES; do
    if ! docker image inspect "$img" >/dev/null 2>&1; then
      ALL_EXIST=false
      break
    fi
  done

  if [ "$ALL_EXIST" = true ] && [ -n "$IMAGES" ]; then
    echo "[$COUNT/$TOTAL] ✓ $name — 镜像已存在，跳过"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # 读取 FLAG
  FLAG_VAL=""
  if [ -f "$dir/.env" ]; then
    FLAG_VAL=$(grep -m1 "^FLAG=" "$dir/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
    if [ -z "$FLAG_VAL" ]; then
      FLAG_VAL=$(grep -m1 "^FLAG1=" "$dir/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
    fi
  fi

  echo "[$COUNT/$TOTAL] 🔨 $name — 构建中..."
  START_TIME=$(date +%s)

  if FLAG="$FLAG_VAL" docker compose -f "$dir/docker-compose.yml" build 2>&1 | tail -5; then
    END_TIME=$(date +%s)
    ELAPSED=$((END_TIME - START_TIME))
    echo "  ✓ 完成 (${ELAPSED}s)"
  else
    END_TIME=$(date +%s)
    ELAPSED=$((END_TIME - START_TIME))
    echo "  ✗ 失败 (${ELAPSED}s)"
    FAILED+=("$name")
  fi
done

echo ""
echo "===== 构建完成 ====="
echo "总计: $TOTAL | 成功: $((COUNT - SKIPPED - ${#FAILED[@]})) | 跳过: $SKIPPED | 失败: ${#FAILED[@]}"
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "失败列表: ${FAILED[*]}"
fi
