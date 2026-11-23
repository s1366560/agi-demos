# 知识与记忆

从 [图投影 worker](workers/graph_projection/worker.py) 读取云端实体与关系转换规则，从 [设备检索实现](workers/device_search/src/lib.rs) 读取按文档查找文本的规则。两种执行器使用同一个知识包发行版本。云端持久化和设备执行权限分别由对应宿主复核。

图谱持久化任务位于 [backend/graph_workflows.py](backend/graph_workflows.py)。完整服务向 Automation 运行时注册事件处理、增量刷新与社区重建任务，各任务在执行和恢复时重新取得作用域授权。

从仓库根目录构建两个目标。发布者提供受信的签名密钥文件和已推送的 OCI 镜像不可变引用。镜像构建步骤见[图投影说明](workers/graph_projection/README.md)。

```sh
cd plugins/business/knowledge
cargo build --locked --release --target wasm32-unknown-unknown --manifest-path workers/device_search/Cargo.toml
PYTHONPATH=../../../sdk/memstack-plugin-sdk/src uv run python build.py \
  --image "$PROJECTION_IMAGE_DIGEST_REF" --version 1.0.0 \
  --wasm workers/device_search/target/wasm32-unknown-unknown/release/memstack_device_knowledge.wasm \
  --key "$PUBLISHER_KEY_FILE" --out knowledge.mspkg
```

在安装页面核对目标及权限。云端图投影使用工具 `project_graph`，设备端使用 `search_documents`。设备目标仍需要当前设备的项目授权。云端重处理与回放的端到端测试在 [test_signed_graph_projection.py](../../../src/tests/integration/test_signed_graph_projection.py)，设备签名与调用回归见 [verify_sidecar.py](workers/device_search/verify_sidecar.py)。
