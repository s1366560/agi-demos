# MemStack 使用示例

本目录包含 MemStack API 的使用示例。

## 基础使用示例

### basic_usage.py

演示如何使用 MemStack API 的基本功能：

1. 创建 Episodes（文本和 JSON 格式）
2. 搜索记忆
3. 查询特定信息

**运行示例：**

```bash
# 1. 确保服务正在运行
make dev

# 2. 在另一个终端运行示例
python examples/basic_usage.py
```

**预期输出：**

```
================================================================================
MemStack API 使用示例
================================================================================

确保服务正在运行: make dev
或只启动基础设施: docker compose up

================================================================================

1. 检查服务健康状态...
   状态: {'status': 'healthy', 'service': 'memstack'}

2. 创建第一个 Episode（用户偏好）...
   响应: {'id': '...', 'status': 'processing', 'message': 'Episode queued for ingestion', 'created_at': '...'}

...
```

## 更多示例（开发中）

- `entity_extraction.py` - 实体提取示例
- `temporal_query.py` - 时态查询示例
- `hybrid_search.py` - 混合检索示例
- `multi_tenant.py` - 多租户使用示例

## Protocol V2 插件分发

V1 Python entry point 与 `.memstack/plugins/*/plugin.py` 本地发现机制已经退役。V2
插件必须通过精确 contract、目标 catalog、Profile layer 和签名 Bundle 进入 generation，
不得在运行时扫描或调用任意 `setup(api)`。

仓库内可执行示例以生产基线为准：

- `config/plugin-manifests-v2/`：跨目标 manifest 与公开 contract
- `config/plugin-profiles/memstack-default.v2.yaml`：基础 Profile entries
- `shared/catalogs/plugin-module-catalog.v2.json`：生成式目标 catalog
- `src/infrastructure/plugins/v2/production_bundle.py`：确定性 `.mspkg` 组装

修改 V2 contract、manifest 或 Profile 后运行：

```bash
make plugin-build-all
```

Marketplace 安装只更新 `DesiredBundleSetV2`；数据面在完整 candidate 验证和健康检查通过后，
才会于新的 generation boundary 原子切换。

## 注意事项

1. 运行示例前，请确保已安装所有依赖：
   ```bash
   uv sync
   ```

2. 确保 Neo4j 和其他依赖服务正在运行

3. 配置好必要的环境变量（`.env` 文件）
