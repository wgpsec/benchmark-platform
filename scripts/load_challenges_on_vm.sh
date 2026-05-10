#!/bin/bash
# 在 Mac 上运行：把预构建的 challenge 镜像传到 VM 并 load
# 用法：VM_HOST=x VM_USER=x VM_PASS=x bash scripts/load_challenges_on_vm.sh

set -e

: "${VM_HOST:?请设置 VM_HOST 环境变量}"
: "${VM_PORT:=22}"
: "${VM_USER:?请设置 VM_USER 环境变量}"
: "${VM_PASS:?请设置 VM_PASS 环境变量}"
SAVE_DIR="$(dirname "$0")/images/challenges"

if [ ! -d "$SAVE_DIR" ] || [ -z "$(ls -A $SAVE_DIR/*.tar 2>/dev/null)" ]; then
  echo "✗ 没找到 challenge tar 文件，请先运行 build_and_save_challenges.sh"
  exit 1
fi

TOTAL=$(ls "$SAVE_DIR"/*.tar 2>/dev/null | wc -l | tr -d ' ')
COUNT=0

for tar in "$SAVE_DIR"/*.tar; do
  fname=$(basename "$tar")
  name="${fname%.tar}"
  COUNT=$((COUNT + 1))

  echo "[$COUNT/$TOTAL] → $name ..."
  sshpass -p "$VM_PASS" scp -o StrictHostKeyChecking=no -P "$VM_PORT" \
    "$tar" "$VM_USER@$VM_HOST:/tmp/$fname"
  sshpass -p "$VM_PASS" ssh -o StrictHostKeyChecking=no -p "$VM_PORT" "$VM_USER@$VM_HOST" \
    "docker load -i /tmp/$fname && rm /tmp/$fname"
  echo "  ✓ loaded"
done

echo ""
echo "===== 全部完成 ($COUNT 个镜像) ====="
echo ""
echo "VM 上镜像总数："
sshpass -p "$VM_PASS" ssh -o StrictHostKeyChecking=no -p "$VM_PORT" "$VM_USER@$VM_HOST" \
  "docker images | wc -l"
