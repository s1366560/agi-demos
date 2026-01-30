# Vanus vs Moltbot 架构与功能对比报告

> 生成时间: 2026-01-30
> 对比版本: vendor/moltbot (当前) vs Vanus (main)

## 一、项目定位对比

| 维度 | Moltbot | Vanus |
|------|---------|----------|
| **目标用户** | 个人用户 | 企业团队 |
| **部署方式** | 本地设备/单机 | 云原生/Docker 编排 |
| **核心理念** | 本地优先、隐私保护 | 多租户、企业级 |
| **主要场景** | 个人 AI 助手、消息渠道集成 | AI 记忆云、知识图谱、Agent 工作流 |

## 二、架构设计对比

### 2.1 架构模式

| 特性 | Moltbot | Vanus |
|------|---------|----------|
| **架构风格** | 分层 + 插件化 | DDD + 六边形架构 |
| **服务粒度** | 单体应用 | 微服务 (API + Workers) |
| **代码组织** | 功能模块化 | 领域驱动 (domain/application/infrastructure) |

### 2.2 架构图对比

**Moltbot 架构**:
```
┌─────────────────────────────────────┐
│   客户端 (macOS/iOS/Android/Web)    │
└─────────────────────────────────────┘
              │ WebSocket
┌─────────────────────────────────────┐
│         Gateway 网关层               │
│    (WebSocket 服务器 + 协议处理)      │
└─────────────────────────────────────┘
              │
┌─────────────────────────────────────┐
│         Agent 代理层                 │
│   (Pi 代理 + 工具执行 + 会话管理)     │
└─────────────────────────────────────┘
              │
┌─────────────────────────────────────┐
│        Channels 渠道层               │
│  (WhatsApp/Telegram/Discord/...)    │
└─────────────────────────────────────┘
```

**Vanus 架构**:
```
┌─────────────────────────────────────┐
│     外部适配器 (Infrastructure)      │
│  Web API | SSE | WebSocket          │
└─────────────────────────────────────┘
              ↑ ↓
┌─────────────────────────────────────┐
│      应用层 (Application)            │
│  Use Cases | App Services | DTOs    │
└─────────────────────────────────────┘
              ↑ ↓
┌─────────────────────────────────────┐
│      领域层 (Domain)                 │
│  Entities | Value Objects | Ports   │
└─────────────────────────────────────┘
```

## 三、技术栈对比

### 3.1 后端技术栈

| 组件 | Moltbot | Vanus |
|------|---------|----------|
| **语言/运行时** | TypeScript/Node.js 22+ | Python 3.12+ |
| **Web 框架** | Hono | FastAPI |
| **数据存储** | SQLite + 文件系统 | PostgreSQL + Neo4j + Redis |
| **工作流** | 内置调度 | Temporal.io |
| **Agent 核心** | @mariozechner/pi-agent-core | 自研 ReAct Agent |
| **LLM 集成** | 直接集成 | LiteLLM (多提供商) |

### 3.2 前端技术栈

| 组件 | Moltbot | Vanus |
|------|---------|----------|
| **框架** | React | React 19.2+ |
| **状态管理** | 未明确 | Zustand 5.0+ |
| **UI 组件** | Ant Design | Ant Design 6.1+ |
| **构建工具** | 未明确 | Vite 7.3+ |
| **样式** | 未明确 | Tailwind CSS 4.1+ |
| **测试** | Vitest + Playwright | Vitest + Playwright |

### 3.3 AI/LLM 能力

| 能力 | Moltbot | Vanus |
|------|---------|----------|
| **LLM 提供商** | Anthropic/OpenAI/Gemini/Qwen | Gemini/Qwen/OpenAI/Deepseek/ZhipuAI |
| **Agent 推理** | Pi 代理 (第三方) | ReAct Agent (自研四层架构) |
| **记忆系统** | Markdown 文件 + 向量搜索 | 知识图谱 (Neo4j) + 混合搜索 |
| **工具策略** | 工具配置文件 | PermissionManager (运行时) |

## 四、核心功能对比

### 4.1 Agent 系统

| 特性 | Moltbot | Vanus |
|------|---------|----------|
| **Agent 架构** | 单层 (Pi 代理) | 四层 (Tool/Skill/SubAgent/Agent) |
| **推理模式** | Pi 内置 | ReAct (思考-行动-观察) |
| **工具执行** | 同步/异步 | 异步 + 重试 + 死循环检测 |
| **成本追踪** | 有 | CostTracker (实时) |
| **权限控制** | 配置文件 | PermissionManager (Allow/Deny/Ask) |

**Vanus 四层架构**:
- **L1 - Tool 层**: 原子能力单元 (Web 搜索、终端操作、计划工具等)
- **L2 - Skill 层**: 声明式工具组合
- **L3 - SubAgent 层**: 专业化代理 (探索型、执行型)
- **L4 - Agent 层**: 完整 ReAct 代理

### 4.2 记忆系统

| 特性 | Moltbot | Vanus |
|------|---------|----------|
| **存储方式** | Markdown 文件 | Neo4j 图数据库 |
| **数据结构** | 线性日志 | 实体-关系-社区图 |
| **搜索能力** | 向量 + 关键词 | 混合搜索 (向量+关键词+RRF) |
| **知识提取** | 手动/简单自动 | LLM 驱动的实体/关系抽取 |
| **社区发现** | 无 | Louvain 算法 |

**Moltbot 双层记忆**:
```
~/clawd/agents/<agentId>/workspace/
├── memory/
│   ├── 2024-01-15.md    # 日志层（追加）
│   └── ...
└── MEMORY.md             # 记忆层（编辑）
```

**Vanus 知识图谱 Schema**:
```
(:Episodic) -[:MENTIONS]-> (:Entity)
(:Entity) -[:RELATES_TO]-> (:Entity)
(:Entity) -[:BELONGS_TO]-> (:Community)
```

### 4.3 消息渠道

| 特性 | Moltbot | Vanus |
|------|---------|----------|
| **支持渠道** | WhatsApp/Telegram/Discord/Slack/iMessage/Signal/Google Chat | API/WebSocket (无直接渠道集成) |
| **集成方式** | 原生 SDK 统一封装 | REST API / SSE |
| **消息格式** | 统一内部格式 | OpenAI 兼容格式 |

### 4.4 代码执行

| 特性 | Moltbot | Vanus |
|------|---------|----------|
| **执行环境** | 本地 shell/进程 | Docker 沙箱 + VNC 桌面 |
| **隔离性** | 进程级 | 容器级 |
| **可视化** | 无 | XFCE 桌面 + noVNC |

## 五、企业级特性对比

| 特性 | Moltbot | Vanus |
|------|---------|----------|
| **多租户** | 无 (单用户) | 有 (Tenant + Project 隔离) |
| **权限管理** | 设备认证 | RBAC + API Key |
| **审计日志** | 无 | 有 |
| **可观测性** | 基础日志 | OpenTelemetry 分布式追踪 |
| **工作流编排** | 内置简单调度 | Temporal.io 企业级 |
| **数据持久化** | 文件系统 | PostgreSQL + Neo4j + Redis |

## 六、目录结构对比

### Moltbot 目录结构
```
vendor/moltbot/
├── src/
│   ├── agents/                   # AI代理相关
│   │   ├── auth-profiles/        # 认证配置文件
│   │   ├── pi-embedded-*        # Pi代理嵌入式集成
│   │   ├── skills/               # 技能系统
│   │   ├── tools/                # 工具定义
│   │   └── tool-policy.ts        # 工具策略管理
│   ├── gateway/                  # 网关核心
│   │   ├── server/               # 服务器实现
│   │   ├── protocol/             # 协议定义
│   │   └── methods/              # 方法处理器
│   ├── channels/                 # 消息渠道
│   │   ├── plugins/              # 渠道插件
│   │   └── registry.ts           # 渠道注册
│   ├── memory/                   # 记忆系统
│   │   ├── manager.ts            # 记忆管理器
│   │   └── embeddings/           # 向量化
│   ├── config/                   # 配置管理
│   └── plugins/                  # 插件系统
├── apps/                         # 移动应用
│   ├── ios/
│   └── android/
├── ui/                          # Web UI
└── docs/                       # 文档
```

### Vanus 目录结构
```
Vanus/
├── src/                          # Python 后端源码
│   ├── domain/                   # 领域层 (DDD)
│   │   ├── model/                # 领域实体
│   │   │   ├── agent/            # Agent 相关领域模型
│   │   │   ├── auth/             # 认证领域模型
│   │   │   ├── memory/           # 记忆领域模型
│   │   │   ├── project/          # 项目领域模型
│   │   │   └── tenant/           # 租户领域模型
│   │   └── ports/                # 端口接口 (依赖倒置)
│   ├── application/              # 应用层
│   │   ├── services/             # 应用服务
│   │   ├── use_cases/            # 业务用例
│   │   └── schemas/              # DTOs
│   ├── infrastructure/           # 基础设施层
│   │   ├── adapters/             # 适配器
│   │   ├── agent/                # ReAct Agent 系统
│   │   ├── graph/                # 知识图谱系统
│   │   ├── llm/                  # LLM 客户端
│   │   └── security/             # 安全认证
│   └── configuration/            # 配置和 DI
├── web/                          # React 前端源码
│   ├── src/
│   │   ├── pages/                # 页面组件
│   │   ├── components/           # 可复用组件
│   │   ├── stores/               # Zustand 状态管理
│   │   ├── services/             # API 服务
│   │   └── hooks/                # 自定义 Hooks
└── docker-compose.yml            # Docker 编排
```

## 七、相同点总结

1. **TypeScript 前端**: 两者都使用 React + TypeScript
2. **插件化设计**: 都支持工具/技能扩展
3. **多 LLM 支持**: 都集成多家 LLM 提供商
4. **流式响应**: 都支持 SSE/流式输出
5. **记忆功能**: 都有持久化记忆和搜索能力
6. **工具系统**: 都有可扩展的工具执行能力
7. **现代开发工具**: 都使用 Vitest + Playwright 测试

## 八、差异点总结

### Moltbot 独有优势

| 特性 | 说明 |
|------|------|
| **消息渠道直接集成** | 支持主流即时通讯平台原生集成 |
| **本地优先** | 数据本地存储，隐私保护 |
| **简单部署** | 单体应用，易于本地运行 |
| **跨平台客户端** | macOS/iOS/Android 全平台支持 |
| **文件系统存储** | 简单直观的 Markdown 记忆 |
| **WebSocket 协议** | 统一的消息协议设计 |
| **设备认证** | 公钥/私钥配对机制 |

### Vanus 独有优势

| 特性 | 说明 |
|------|------|
| **知识图谱** | Neo4j 驱动的实体关系图 |
| **企业级工作流** | Temporal.io 编排 |
| **多租户架构** | 完整的租户和项目隔离 |
| **自研 Agent** | 四层 ReAct Agent 架构 |
| **代码执行沙箱** | Docker + VNC 桌面环境 |
| **混合搜索** | 向量 + 关键词 + RRF 融合 |
| **社区检测** | Louvain 算法知识聚类 |
| **RBAC 权限** | 完整的基于角色访问控制 |
| **API Key 认证** | SHA256 哈希的安全 API Key |

## 九、API 设计对比

### Moltbot WebSocket 协议
```typescript
// 握手请求
{
  "type": "req",
  "id": "1",
  "method": "connect",
  "params": {
    "role": "operator",
    "scopes": ["operator.read", "operator.write"],
    "device": {
      "id": "device_fingerprint",
      "publicKey": "...",
      "signature": "..."
    }
  }
}

// 握手响应
{
  "type": "res",
  "id": "1",
  "ok": true,
  "payload": {
    "type": "hello-ok",
    "protocol": 3,
    "auth": { "deviceToken": "..." }
  }
}
```

### Vanus REST API
```
/api/v1/
├── auth/                    # 认证相关
├── tenants/                 # 租户管理
├── projects/                # 项目管理
├── agent/                   # Agent 服务
│   ├── /chat               # Agent 聊天 (SSE)
│   ├── /tools/             # 工具列表
│   ├── /skills/            # 技能管理
│   └── /conversations/     # 对话管理
├── memories/                # 记忆服务
├── sandbox/                 # 沙箱服务
└── llm/                     # LLM 服务
```

## 十、架构复杂度评估

| 维度 | Moltbot | Vanus |
|------|---------|----------|
| **代码规模** | 中等 | 大型 |
| **学习曲线** | 低-中 | 中-高 |
| **部署复杂度** | 低 | 高 (需 Docker 编排) |
| **扩展性** | 插件级 | 微服务级 |
| **维护成本** | 低-中 | 中-高 |

## 十一、总结与建议

### 11.1 适用场景

**Moltbot 适合**:
- 个人用户
- 隐私敏感场景
- 快速部署需求
- 消息渠道集成需求
- 本地开发/测试

**Vanus 适合**:
- 企业团队协作
- 知识管理系统
- 复杂工作流编排
- 多租户 SaaS 平台
- 需要知识图谱的场景

### 11.2 Vanus 可借鉴 Moltbot 的设计

1. **插件化架构**: Moltbot 的渠道插件系统设计优雅
2. **WebSocket 协议**: 统一的消息协议设计值得参考
3. **文件系统简单性**: 某些场景下文件存储比数据库更直观
4. **设备认证**: 公钥/私钥配对机制安全性好
5. **移动应用**: iOS/Android 原生应用经验

### 11.3 Moltbot 可借鉴 Vanus 的设计

1. **知识图谱**: Neo4j 的图结构比文件系统更强大
2. **企业级特性**: 多租户、权限、审计是 B 端必备
3. **工作流编排**: Temporal.io 比内置调度更可靠
4. **代码执行沙箱**: Docker 桌面环境更安全可控
5. **DDD 架构**: 六边形架构更易于测试和扩展

## 十二、附录：关键依赖对比

### Moltbot 关键依赖
```json
{
  "@mariozechner/pi-agent-core": "0.49.3",
  "@whiskeysockets/baileys": "7.0.0-rc.9",
  "grammy": "^1.39.3",
  "@slack/bolt": "^4.6.0",
  "hono": "4.11.4",
  "sqlite-vec": "0.1.7-alpha.2"
}
```

### Vanus 关键依赖
```python
# 后端
fastapi = ">=0.110.0"
pydantic = ">=2.5.0"
sqlalchemy = ">=2.0.0"
neo4j = ">=5.26.0"
redis = ">=5.0.0"
litellm = ">=1.0.0"
temporalio = ">=1.0.0"

# 前端
react = "19.2.0"
typescript = "5.9.0"
vite = "7.3.0"
zustand = "5.0.0"
antd = "6.1.0"
```

---

**文档版本**: 1.0
**最后更新**: 2026-01-30
