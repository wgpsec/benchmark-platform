#!/bin/bash
# 在 Mac 上运行：把保存好的镜像传到 VM 并 load
# 用法：VM_HOST=x VM_USER=x VM_PASS=x bash scripts/load_on_vm.sh

set -e

: "${VM_HOST:?请设置 VM_HOST 环境变量}"
: "${VM_PORT:=22}"
: "${VM_USER:?请设置 VM_USER 环境变量}"
: "${VM_PASS:?请设置 VM_PASS 环境变量}"
SAVE_DIR="$(dirname "$0")/images"

if [ ! -d "$SAVE_DIR" ] || [ -z "$(ls -A $SAVE_DIR/*.tar 2>/dev/null)" ]; then
  echo "✗ 没找到 tar 文件，请先运行 pull_and_save.sh"
  exit 1
fi

# 在 VM 上建目录
sshpass -p "$VM_PASS" ssh -o StrictHostKeyChecking=no -p "$VM_PORT" "$VM_USER@$VM_HOST" \
  "mkdir -p /tmp/docker-images"

for tar in "$SAVE_DIR"/*.tar; do
  fname=$(basename "$tar")
  echo "→ 传输 $fname ..."
  sshpass -p "$VM_PASS" scp -o StrictHostKeyChecking=no -P "$VM_PORT" \
    "$tar" "$VM_USER@$VM_HOST:/tmp/docker-images/$fname"
  echo "  加载中 ..."
  sshpass -p "$VM_PASS" ssh -o StrictHostKeyChecking=no -p "$VM_PORT" "$VM_USER@$VM_HOST" \
    "docker load -i /tmp/docker-images/$fname && rm /tmp/docker-images/$fname"
  echo "  ✓ 完成 $fname"
done

echo ""
echo "VM 上已加载的镜像："
sshpass -p "$VM_PASS" ssh -o StrictHostKeyChecking=no -p "$VM_PORT" "$VM_USER@$VM_HOST" \
  "docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}'"
