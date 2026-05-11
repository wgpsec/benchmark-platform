## 部署脚本

在 Mac 上预构建镜像并传输到 VM：

```bash
# 1. 构建所有 challenge 镜像
bash scripts/build_and_save_challenges.sh

# 2. 传输到 VM
VM_HOST=10.x.x.x VM_PORT=22 VM_USER=root VM_PASS=xxx \
  bash scripts/load_challenges_on_vm.sh

# 3. 在 VM 上预构建（如果未通过镜像传输）
bash scripts/prebuild_on_vm.sh
```
