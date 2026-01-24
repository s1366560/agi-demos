# Graphiti 依赖移除与自研知识图谱系统计划

## 概述

移除 `vendor/graphiti` 依赖，实现自研的知识图谱处理系统。保持 `GraphServicePort` 接口不变，用 `NativeGraphAdapter` 替代 `GraphitiAdapter`。

## 1. 背景分析

### 1.1 当前 Graphiti 使用情况

**核心依赖点**（位于 `src/infrastructure/adapters/secondary/graphiti/graphiti_adapter.py`）：

| 方法 | Graphiti 使用 | 可替代性 |
|------|--------------|---------|
| `add_episode()` | 仅创建 Episodic 节点（Cypher） | 已是直接 Cypher |
| `search()` | `graphiti_client.search_()` | 需自研混合搜索 |
| `get_graph_data()` | 直接 Cypher 查询 | 已是直接 Cypher |
| `delete_*()` | 直接 Cypher 查询 | 已是直接 Cypher |

**后台任务处理**（位于 `src/application/tasks/episode.py:91`）：
```python
# 这是唯一真正使用 Graphiti 核心功能的地方
add_result = await queue_service._graphiti_client.add_episode(...)
```

**实际依赖的 Graphiti 模块**：
- `graphiti_core.Graphiti` - 主类
- `graphiti_core.add_episode()` - 实体抽取 + 关系发现 + 向量嵌入
- `graphiti_core.search_()` - 混合搜索
- `graphiti_core.helpers.semaphore_gather` - 并发控制
- `graphiti_core.utils.maintenance.community_operations.update_community` - 社群更新

### 1.2 Graphiti 核心处理流程（需要自研替代）

```
add_episode() 内部流程：
1. 实体抽取 (extract_nodes) - LLM 驱动
2. 反射迭代 (reflexion) - 可选，检查遗漏
3. 实体去重 (dedupe_nodes) - 与图中已有实体合并
4. 向量嵌入生成 (create_embeddings)
5. 关系发现 (extract_edges) - LLM 驱动
6. 关系去重/更新权重
7. 保存到 Neo4j
```

### 1.3 已有可复用组件

- **LiteLLM 集成** - `src/infrastructure/llm/litellm/`
- **向量嵌入服务** - 已有 Qwen/Gemini/OpenAI embedder
- **Neo4j 直接访问** - GraphitiAdapter 已大量使用 Cypher
- **维度管理工具** - `embedding_utils.py` 已实现维度检查和清理

## 2. 模块设计

### 2.1 新模块结构

```
src/infrastructure/graph/
├── __init__.py
├── native_graph_adapter.py        # 新适配器，实现 GraphServicePort
├── neo4j_client.py                # Neo4j 驱动封装（复用现有连接）
├── extraction/
│   ├── __init__.py
│   ├── entity_extractor.py        # 实体抽取器（LiteLLM）
│   ├── relationship_extractor.py  # 关系发现器（LiteLLM）
│   └── prompts.py                 # Prompt 模板
├── embedding/
│   ├── __init__.py
│   └── embedding_service.py       # 向量嵌入服务包装
├── search/
│   ├── __init__.py
│   └── hybrid_search.py           # 混合搜索（向量 + 关键词 + RRF）
└── community/
    ├── __init__.py
    └── community_updater.py       # 社群更新（简化版）
```

### 2.2 核心类设计

**NativeGraphAdapter**（替代 GraphitiAdapter）：
```python
class NativeGraphAdapter(GraphServicePort):
    def __init__(
        self,
        neo4j_driver: Neo4jDriver,
        llm_client: LLMClient,      # 来自 LiteLLM
        embedder: EmbedderService,
        queue_port: Optional[QueuePort] = None,
    ):
        self.entity_extractor = EntityExtractor(llm_client, embedder)
        self.relationship_extractor = RelationshipExtractor(llm_client)
        self.hybrid_search = HybridSearch(neo4j_driver, embedder)
        self.community_updater = CommunityUpdater(llm_client)
```

**EntityExtractor**（实体抽取）：
```python
class EntityExtractor:
    async def extract(
        self,
        content: str,
        entity_types: Optional[dict] = None,
        project_id: str = None,
    ) -> List[EntityNode]:
        # 1. 构建 Prompt
        # 2. 调用 LLM (结构化输出)
        # 3. 生成向量嵌入
        # 4. 返回 EntityNode 列表
```

**HybridSearch**（混合搜索）：
```python
class HybridSearch:
    async def search(
        self,
        query: str,
        project_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict]:
        # 1. 并行执行向量搜索 + 关键词搜索
        # 2. RRF 融合
        # 3. 返回混合结果
```

## 3. Neo4j 图模型

### 3.1 节点定义（保持与 Graphiti 兼容）

```cypher
-- Episodic 节点（保持不变）
(:Episodic:Node {
    uuid: String,
    name: String,
    content: String,
    source_description: String,
    source: String,
    created_at: DateTime,
    valid_at: DateTime,
    group_id: String,
    tenant_id: String,
    project_id: String,
    user_id: String,
    memory_id: String,
    status: String,          -- Processing/Synced/Failed
    entity_edges: [String]   -- 关联的边 UUID
})

-- Entity 节点（保持不变）
(:Entity:Node {
    uuid: String,
    name: String,
    entity_type: String,
    summary: String,
    created_at: DateTime,
    tenant_id: String,
    project_id: String,
    user_id: String,
    name_embedding: [Float],  -- 向量嵌入
    attributes: Map
})

-- Community 节点
(:Community {
    uuid: String,
    name: String,
    summary: String,
    member_count: Integer,
    tenant_id: String,
    project_id: String
})
```

### 3.2 关系定义（保持不变）

```cypher
-- MENTIONS: Episode -> Entity
(ep:Episodic)-[:MENTIONS]->(e:Entity)

-- RELATES_TO: Entity -> Entity
(e1:Entity)-[:RELATES_TO {
    uuid: String,
    relationship_type: String,
    weight: Float,
    episodes: [String],
    created_at: DateTime
}]->(e2:Entity)

-- BELONGS_TO: Entity -> Community
(e:Entity)-[:BELONGS_TO]->(c:Community)
```

## 4. 实现计划

### Phase 1: 基础设施（预计 3-4 天）

**任务清单**：
- [ ] 创建 `src/infrastructure/graph/` 目录结构
- [ ] 实现 `neo4j_client.py` - 封装 Neo4j 驱动（复用现有连接逻辑）
- [ ] 实现 `embedding_service.py` - 包装现有向量嵌入服务
- [ ] 定义 Pydantic 模型用于 LLM 结构化输出

**关键文件**：
- `src/infrastructure/graph/neo4j_client.py`
- `src/infrastructure/graph/embedding/embedding_service.py`
- `src/infrastructure/graph/schemas.py` (节点/边的 Pydantic 模型)

### Phase 2: 实体抽取模块（预计 3-4 天）

**任务清单**：
- [ ] 实现 `prompts.py` - 设计实体抽取 Prompt
- [ ] 实现 `entity_extractor.py` - LLM 调用 + 结构化输出解析
- [ ] 实现实体去重逻辑（向量相似度匹配）
- [ ] 单元测试

**关键文件**：
- `src/infrastructure/graph/extraction/prompts.py`
- `src/infrastructure/graph/extraction/entity_extractor.py`
- `src/tests/unit/graph/test_entity_extractor.py`

**Prompt 设计要点**：
```python
ENTITY_EXTRACTION_PROMPT = """
从以下文本中提取所有重要实体。

实体类型：{entity_types}

文本：
{content}

输出 JSON 格式：
{
  "entities": [
    {"name": "实体名称", "type": "类型", "summary": "简短描述"}
  ]
}
"""
```

### Phase 3: 关系发现模块（预计 2-3 天）

**任务清单**：
- [ ] 实现关系发现 Prompt
- [ ] 实现 `relationship_extractor.py` - 发现实体间关系
- [ ] 实现权重计算逻辑
- [ ] 单元测试

**关键文件**：
- `src/infrastructure/graph/extraction/relationship_extractor.py`
- `src/tests/unit/graph/test_relationship_extractor.py`

### Phase 4: 搜索模块（预计 2-3 天）

**任务清单**：
- [ ] 实现向量搜索（Neo4j Vector Index）
- [ ] 实现关键词搜索
- [ ] 实现 RRF 融合算法
- [ ] 实现 `hybrid_search.py`
- [ ] 单元测试

**关键文件**：
- `src/infrastructure/graph/search/hybrid_search.py`
- `src/tests/unit/graph/test_hybrid_search.py`

**RRF 融合公式**：
```python
def rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (rank + k)
```

### Phase 5: 适配器集成（预计 3-4 天）

**任务清单**：
- [ ] 实现 `native_graph_adapter.py`（实现 GraphServicePort）
- [ ] 实现 `community_updater.py`（简化版社群更新）
- [ ] 创建新的 `EpisodeTaskHandler` 逻辑
- [ ] 更新 DI 容器（添加功能开关）
- [ ] 集成测试

**关键文件**：
- `src/infrastructure/graph/native_graph_adapter.py`
- `src/infrastructure/graph/community/community_updater.py`
- `src/configuration/di_container.py`（添加工厂方法）
- `src/tests/integration/graph/test_native_graph_adapter.py`

**DI 容器更新**：
```python
# 在 config.py 添加
USE_NATIVE_GRAPH_ADAPTER: bool = False

# 在 di_container.py 添加
def graph_service(self) -> GraphServicePort:
    if settings.USE_NATIVE_GRAPH_ADAPTER:
        return NativeGraphAdapter(...)
    else:
        return GraphitiAdapter(...)  # 保持现有逻辑
```

### Phase 6: 测试与验证（预计 3-4 天）

**任务清单**：
- [ ] 完善单元测试（覆盖率 > 80%）
- [ ] 集成测试（端到端流程）
- [ ] 对比测试（Graphiti vs Native）
- [ ] 性能测试

**测试策略**：
```python
# 对比测试示例
async def test_entity_extraction_comparison():
    content = "张三是ABC公司的CEO，公司位于北京。"
    
    # Graphiti 结果
    graphiti_result = await graphiti_adapter.add_episode(...)
    
    # Native 结果
    native_result = await native_adapter.add_episode(...)
    
    # 对比实体数量和类型
    assert len(native_result.entities) >= len(graphiti_result.entities) * 0.8
```

### Phase 7: 切换与清理（预计 2 天）

**任务清单**：
- [ ] 设置 `USE_NATIVE_GRAPH_ADAPTER=true`
- [ ] 灰度测试（部分项目）
- [ ] 全量切换
- [ ] 删除 `vendor/graphiti/` 目录
- [ ] 删除 `GraphitiAdapter` 相关代码
- [ ] 更新文档

## 5. 关键实现细节

### 5.1 LLM 结构化输出

使用 LiteLLM 的 JSON 模式：
```python
async def extract_entities(self, content: str) -> List[Entity]:
    response = await self.llm_client.chat.completions.create(
        model=self.model,
        messages=[
            {"role": "system", "content": ENTITY_SYSTEM_PROMPT},
            {"role": "user", "content": content}
        ],
        response_format={"type": "json_object"}
    )
    
    result = json.loads(response.choices[0].message.content)
    return [Entity(**e) for e in result["entities"]]
```

### 5.2 向量搜索 Cypher

```cypher
-- 向量搜索
CALL db.index.vector.queryNodes(
    'entity_name_vector',
    $limit,
    $query_embedding
)
YIELD node, score
WHERE node.project_id = $project_id OR $project_id IS NULL
RETURN node, score
ORDER BY score DESC
```

### 5.3 实体去重逻辑

```python
async def dedupe_entities(
    self,
    new_entities: List[Entity],
    project_id: str
) -> List[Entity]:
    """
    去重逻辑：
    1. 向量搜索找相似实体
    2. 名称完全匹配 -> 复用
    3. 相似度 > 0.95 且类型相同 -> 复用
    4. 否则创建新实体
    """
```

### 5.4 后台任务处理（新逻辑）

```python
# src/application/tasks/episode.py (更新后)
async def process(self, payload: Dict[str, Any], context: Any) -> None:
    # 1. 实体抽取
    entities = await self.entity_extractor.extract(content, entity_types)
    
    # 2. 实体去重
    unique_entities = await self.entity_extractor.dedupe(entities, project_id)
    
    # 3. 保存实体节点 + MENTIONS 关系
    await self._save_entities(episode_uuid, unique_entities)
    
    # 4. 关系发现
    relationships = await self.relationship_extractor.extract(
        content, unique_entities, edge_types
    )
    
    # 5. 保存关系
    await self._save_relationships(episode_uuid, relationships)
    
    # 6. 更新状态
    await self._update_episode_status(episode_uuid, "Synced")
    
    # 7. 社群更新
    await self.community_updater.update(unique_entities)
```

## 6. 用户确认的设计决策

### 6.1 社群功能：完整版实现
实现完整的图聚类算法，自动发现社群：
- 使用 Louvain 或类似算法进行社群检测
- 为社群生成摘要（LLM 驱动）
- 维护 Entity -> Community 的 BELONGS_TO 关系
- 新增文件：`src/infrastructure/graph/community/louvain_detector.py`

### 6.2 反射迭代：保留
保留反射迭代功能以确保不遗漏重要实体：
```python
# 实体抽取流程
async def extract_with_reflexion(content: str) -> List[Entity]:
    # 第一次抽取
    entities = await self._extract(content)
    
    # 反射检查
    missed = await self._check_missed_entities(content, entities)
    
    # 合并结果
    if missed:
        entities.extend(missed)
    
    return entities
```
**注意**：这会增加约 2 倍的 LLM 调用成本，但能提高实体召回率。

### 6.3 实施顺序：按计划顺序
按照 Phase 1-7 的顺序依次实施，确保基础设施完善后再实现上层功能。

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 提取质量下降 | 实体/关系准确性 | 精心设计 Prompt；Few-shot examples |
| 性能下降 | 处理速度 | 批量操作；并发控制；缓存 |
| 搜索质量变化 | 用户体验 | 对比测试；RRF 参数调优 |
| 数据不一致 | 新旧系统差异 | 灰度发布；对比验证 |

## 7. 验证计划

### 功能验证
```bash
# 单元测试
uv run pytest src/tests/unit/graph/ -v

# 集成测试
uv run pytest src/tests/integration/graph/ -v

# 对比测试（需要同时配置两个适配器）
uv run pytest src/tests/comparison/ -v
```

### 端到端验证
1. 启动服务：`make dev`
2. 创建测试 Memory
3. 验证实体抽取结果
4. 验证搜索功能
5. 验证图数据可视化

### 性能验证
```bash
# 性能测试
uv run pytest src/tests/performance/graph/ -v --benchmark
```

## 8. 文件清单（需修改/新增）

### 新增文件
- `src/infrastructure/graph/__init__.py`
- `src/infrastructure/graph/native_graph_adapter.py`
- `src/infrastructure/graph/neo4j_client.py`
- `src/infrastructure/graph/schemas.py`
- `src/infrastructure/graph/extraction/__init__.py`
- `src/infrastructure/graph/extraction/entity_extractor.py`
- `src/infrastructure/graph/extraction/relationship_extractor.py`
- `src/infrastructure/graph/extraction/reflexion.py`
- `src/infrastructure/graph/extraction/prompts.py`
- `src/infrastructure/graph/embedding/__init__.py`
- `src/infrastructure/graph/embedding/embedding_service.py`
- `src/infrastructure/graph/search/__init__.py`
- `src/infrastructure/graph/search/hybrid_search.py`
- `src/infrastructure/graph/community/__init__.py`
- `src/infrastructure/graph/community/louvain_detector.py`
- `src/infrastructure/graph/community/community_updater.py`

### 修改文件
- `src/configuration/config.py` - 添加 `USE_NATIVE_GRAPH_ADAPTER` 开关
- `src/configuration/di_container.py` - 添加 NativeGraphAdapter 工厂
- `src/configuration/factories.py` - 创建新适配器依赖
- `src/application/tasks/episode.py` - 更新任务处理逻辑（条件分支）

### 最终删除（Phase 7）
- `vendor/graphiti/` - 整个目录
- `src/infrastructure/adapters/secondary/graphiti/` - GraphitiAdapter 相关

## 9. 预计工期

| 阶段 | 工期 | 累计 |
|------|------|------|
| Phase 1: 基础设施 | 3-4 天 | 4 天 |
| Phase 2: 实体抽取 | 3-4 天 | 8 天 |
| Phase 3: 关系发现 | 2-3 天 | 11 天 |
| Phase 4: 搜索模块 | 2-3 天 | 14 天 |
| Phase 5: 适配器集成 | 3-4 天 | 18 天 |
| Phase 6: 测试验证 | 3-4 天 | 22 天 |
| Phase 7: 切换清理 | 2 天 | 24 天 |

**总工期：约 4-5 周**

## 10. 成功标准

- [ ] 所有单元测试通过（覆盖率 > 80%）
- [ ] 集成测试通过
- [ ] 对比测试：实体抽取准确率 >= Graphiti 90%
- [ ] 对比测试：搜索结果相关性 >= Graphiti 90%
- [ ] 性能测试：处理速度 >= Graphiti（或在可接受范围）
- [ ] 无数据丢失或损坏
- [ ] `vendor/graphiti/` 完全删除
