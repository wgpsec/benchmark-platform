#!/bin/bash
# 在 Mac 上运行：pull 所有基础镜像并打包
# 用法：bash scripts/pull_and_save.sh

set -e
SAVE_DIR="$(dirname "$0")/images"
mkdir -p "$SAVE_DIR"

# mysql:5.7 没有 arm64 官方镜像，用 8.0 替代
IMAGES=(
  "debian:bullseye-slim"
  "haproxy:2.0.5"
  "httpd:2.4.49"
  "httpd:2.4.50"
  "maven:3.8.4-openjdk-17-slim"
  "mitmproxy/mitmproxy:6.0.2"
  "mysql:8.0"
  "mysql:8.4"
  "nginx:alpine"
  "node:16-alpine"
  "node:20-alpine"
  "node:21"
  "php:5-apache"
  "php:7.1-apache"
  "php:7.4-apache"
  "php:7.4-fpm"
  "php:8.0-apache"
  "php:8.3.6-apache"
  "python:2.7-slim-stretch"
  "python:3.10-slim"
  "python:3.12"
  "python:3.8-slim"
  "python:3.8-slim-buster"
  "python:3.9-slim"
  "ruby:3.1.2"
  "tiangolo/uvicorn-gunicorn-fastapi:python3.9"
  "tomcat:9-jdk17-openjdk-slim"
  "ubuntu:20.04"
  "wordpress:latest"
)

for img in "${IMAGES[@]}"; do
  fname="${img//\//_}"
  fname="${fname//:/_}.tar"
  if [ -f "$SAVE_DIR/$fname" ]; then
    echo "✓ 已存在 $img，跳过"
    continue
  fi
  echo "→ pulling $img ..."
  if docker pull --platform linux/arm64 "$img" -q; then
    echo "  saving ..."
    docker save "$img" -o "$SAVE_DIR/$fname"
    echo "  ✓ 保存到 $fname"
  else
    echo "  ✗ pull 失败，跳过 $img"
  fi
done

# mysql:5.7 arm64 不存在，手动打 tag 让 Dockerfile 能用
echo ""
echo "→ 为 mysql:5.7 打 tag（指向 mysql:8.0）..."
docker tag mysql:8.0 mysql:5.7 2>/dev/null && echo "  ✓ mysql:5.7 tag OK" || echo "  ✗ 请先确保 mysql:8.0 pull 成功"

echo ""
echo "全部完成，镜像保存在 $SAVE_DIR"
echo "文件列表："
ls -lh "$SAVE_DIR"
