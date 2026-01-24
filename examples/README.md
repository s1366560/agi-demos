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
python -m server.main

# 2. 在另一个终端运行示例
python examples/basic_usage.py
```

**预期输出：**

```
================================================================================
MemStack API 使用示例
================================================================================

确保服务正在运行: python -m server.main
或使用 Docker Compose: docker-compose up

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

## 注意事项

1. 运行示例前，请确保已安装所有依赖：
   ```bash
   uv sync
   ```

2. 确保 Neo4j 和其他依赖服务正在运行

3. 配置好必要的环境变量（`.env` 文件）
