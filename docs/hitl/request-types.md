# HITL 请求类型详解

本文档详细说明 HITL 系统支持的 4 种请求类型。

## 概览

| 类型 | 枚举值 | 用途 | 典型超时 |
|------|--------|------|---------|
| Clarification | `clarification` | 澄清用户意图 | 300s |
| Decision | `decision` | 关键决策点 | 300s |
| EnvVar | `env_var` | 收集环境变量 | 300s |
| Permission | `permission` | 授权敏感操作 | 60s |

---

## 1. Clarification (澄清请求)

当 Agent 无法确定用户意图时，请求澄清。

### 使用场景

- 用户指令模糊不清
- 存在多种可能的理解方式
- 需要确认前提条件

### 数据结构

```python
@dataclass
class ClarificationRequestData:
    question: str                              # 澄清问题
    clarification_type: ClarificationType      # 澄清类型
    options: List[ClarificationOption]         # 预设选项
    allow_custom: bool = True                  # 允许自定义回答
    context: Dict[str, Any] = {}               # 上下文信息
    default_value: Optional[str] = None        # 默认值

class ClarificationType(str, Enum):
    SCOPE = "scope"              # 任务范围
    APPROACH = "approach"        # 实现方式
    PREREQUISITE = "prerequisite"  # 前提条件
    PRIORITY = "priority"        # 优先级
    CONFIRMATION = "confirmation"  # 确认
    CUSTOM = "custom"            # 自定义
```

### 选项结构

```python
@dataclass
class ClarificationOption:
    id: str                     # 选项 ID
    label: str                  # 显示标签
    description: Optional[str]  # 详细描述
    recommended: bool = False   # 是否推荐
```

### 示例

```python
# Agent 代码
response = await handler.request_clarification(
    question="您要处理哪个目录下的文件？",
    clarification_type=ClarificationType.SCOPE,
    options=[
        ClarificationOption(id="current", label="当前目录", recommended=True),
        ClarificationOption(id="recursive", label="递归所有子目录"),
        ClarificationOption(id="specific", label="指定目录"),
    ],
    allow_custom=True,
    timeout_seconds=300,
)
```

### 前端渲染

```tsx
// ClarificationPanel
<Card title="需要澄清">
  <p>{request.question}</p>
  <Radio.Group>
    {request.options.map(opt => (
      <Radio key={opt.id} value={opt.id}>
        {opt.label}
        {opt.recommended && <Tag color="blue">推荐</Tag>}
      </Radio>
    ))}
  </Radio.Group>
  {request.allowCustom && (
    <Input placeholder="或输入自定义回答..." />
  )}
</Card>
```

### 响应格式

```json
{
  "request_id": "clar_12345678",
  "answer": "current"
}
```

---

## 2. Decision (决策请求)

在关键执行点请求用户做出决策。

### 使用场景

- 存在多种实现方式
- 操作有不同风险等级
- 需要在分支间选择

### 数据结构

```python
@dataclass
class DecisionRequestData:
    question: str                          # 决策问题
    decision_type: DecisionType            # 决策类型
    options: List[DecisionOption]          # 决策选项
    allow_custom: bool = False             # 允许自定义 (默认不允许)
    default_option: Optional[str] = None   # 默认选项
    max_selections: Optional[int] = None   # 最大选择数 (多选时)
    context: Dict[str, Any] = {}           # 上下文

class DecisionType(str, Enum):
    BRANCH = "branch"            # 执行分支
    METHOD = "method"            # 实现方法
    CONFIRMATION = "confirmation"  # 风险确认
    RISK = "risk"                # 风险接受
    SINGLE_CHOICE = "single_choice"  # 单选
    MULTI_CHOICE = "multi_choice"   # 多选
    CUSTOM = "custom"            # 自定义
```

### 选项结构

```python
@dataclass
class DecisionOption:
    id: str                              # 选项 ID
    label: str                           # 显示标签
    description: Optional[str]           # 详细描述
    recommended: bool = False            # 是否推荐
    risk_level: Optional[RiskLevel]      # 风险等级
    estimated_time: Optional[str]        # 预估时间
    estimated_cost: Optional[str]        # 预估成本
    risks: List[str] = []                # 风险列表

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

### 示例

```python
# Agent 代码
decision = await handler.request_decision(
    question="选择部署策略",
    decision_type=DecisionType.BRANCH,
    options=[
        DecisionOption(
            id="rolling",
            label="滚动更新",
            description="逐步替换实例，零停机",
            recommended=True,
            risk_level=RiskLevel.LOW,
            estimated_time="10分钟",
        ),
        DecisionOption(
            id="blue_green",
            label="蓝绿部署",
            description="准备新环境后切换",
            risk_level=RiskLevel.MEDIUM,
            estimated_time="20分钟",
            estimated_cost="2x 资源成本",
        ),
        DecisionOption(
            id="canary",
            label="金丝雀发布",
            description="先部署到小部分流量",
            risk_level=RiskLevel.LOW,
            estimated_time="30分钟",
        ),
    ],
    timeout_seconds=300,
)
```

### 前端渲染

```tsx
// DecisionPanel
<Card title="需要决策">
  <p>{request.question}</p>
  <Space direction="vertical" style={{ width: '100%' }}>
    {request.options.map(opt => (
      <Card 
        key={opt.id} 
        size="small"
        onClick={() => setSelected(opt.id)}
        className={selected === opt.id ? 'selected' : ''}
      >
        <div className="option-header">
          <span>{opt.label}</span>
          {opt.recommended && <Tag color="green">推荐</Tag>}
          {opt.riskLevel && <Tag color={riskColors[opt.riskLevel]}>{opt.riskLevel}</Tag>}
        </div>
        {opt.description && <p className="description">{opt.description}</p>}
        {opt.estimatedTime && <span>预计: {opt.estimatedTime}</span>}
      </Card>
    ))}
  </Space>
</Card>
```

### 响应格式

```json
{
  "request_id": "deci_12345678",
  "decision": "rolling"
}
```

---

## 3. EnvVar (环境变量请求)

收集 Agent 执行所需的环境变量或凭证。

### 使用场景

- 需要 API Key
- 需要数据库连接字符串
- 需要访问令牌

### 数据结构

```python
@dataclass
class EnvVarRequestData:
    tool_name: str                   # 需要变量的工具名
    fields: List[EnvVarField]        # 需要收集的字段
    message: Optional[str] = None    # 提示消息
    allow_save: bool = True          # 允许保存供未来使用
    context: Dict[str, Any] = {}     # 上下文

@dataclass
class EnvVarField:
    name: str                        # 变量名 (e.g., "OPENAI_API_KEY")
    label: str                       # 显示标签
    description: Optional[str]       # 描述
    required: bool = True            # 是否必填
    secret: bool = False             # 是否敏感 (掩码显示)
    input_type: EnvVarInputType      # 输入类型
    default_value: Optional[str]     # 默认值
    placeholder: Optional[str]       # 占位符
    pattern: Optional[str]           # 验证正则

class EnvVarInputType(str, Enum):
    TEXT = "text"
    PASSWORD = "password"
    URL = "url"
    API_KEY = "api_key"
    FILE_PATH = "file_path"
```

### 示例

```python
# Agent 代码
env_vars = await handler.request_env_var(
    tool_name="openai_chat",
    fields=[
        EnvVarField(
            name="OPENAI_API_KEY",
            label="OpenAI API Key",
            description="用于调用 GPT 模型",
            secret=True,
            input_type=EnvVarInputType.API_KEY,
            placeholder="sk-...",
            pattern=r"^sk-[a-zA-Z0-9]{48}$",
        ),
        EnvVarField(
            name="OPENAI_ORG_ID",
            label="组织 ID (可选)",
            required=False,
            input_type=EnvVarInputType.TEXT,
        ),
    ],
    message="需要 OpenAI API 凭证来执行此操作",
    allow_save=True,
    timeout_seconds=300,
)
```

### 前端渲染

```tsx
// EnvVarPanel
<Card title="需要环境变量">
  <Alert message={request.message} type="info" />
  <Form layout="vertical">
    {request.fields.map(field => (
      <Form.Item
        key={field.name}
        label={field.label}
        required={field.required}
        help={field.description}
      >
        <Input
          type={field.secret ? 'password' : 'text'}
          placeholder={field.placeholder}
          defaultValue={field.defaultValue}
        />
      </Form.Item>
    ))}
    {request.allowSave && (
      <Checkbox>保存供未来使用</Checkbox>
    )}
  </Form>
</Card>
```

### 响应格式

```json
{
  "request_id": "env_12345678",
  "values": {
    "OPENAI_API_KEY": "sk-xxx...",
    "OPENAI_ORG_ID": "org-xxx"
  },
  "save": true
}
```

---

## 4. Permission (权限请求)

请求用户授权执行敏感操作。

### 使用场景

- 执行危险命令 (rm, drop table)
- 访问敏感数据
- 修改系统配置
- 发送外部请求

### 数据结构

```python
@dataclass
class PermissionRequestData:
    tool_name: str                           # 工具名
    action: str                              # 操作描述
    risk_level: RiskLevel = RiskLevel.MEDIUM # 风险等级
    details: Dict[str, Any] = {}             # 操作详情
    description: Optional[str] = None        # 详细描述
    allow_remember: bool = True              # 允许记住选择
    default_action: Optional[PermissionAction] = None  # 默认操作
    context: Dict[str, Any] = {}             # 上下文

class PermissionAction(str, Enum):
    ALLOW = "allow"              # 允许此次
    DENY = "deny"                # 拒绝此次
    ALLOW_ALWAYS = "allow_always"  # 始终允许此工具
    DENY_ALWAYS = "deny_always"    # 始终拒绝此工具
```

### 示例

```python
# Agent 代码
permission = await handler.request_permission(
    tool_name="shell_execute",
    action="rm -rf ./temp/*",
    risk_level=RiskLevel.HIGH,
    description="删除 temp 目录下的所有文件",
    details={
        "command": "rm -rf ./temp/*",
        "affected_files": 42,
        "total_size": "1.2GB",
    },
    allow_remember=True,
    timeout_seconds=60,  # 权限请求通常超时更短
)

if permission == PermissionAction.DENY:
    raise PermissionDeniedException("用户拒绝执行此命令")
```

### 前端渲染

```tsx
// PermissionPanel
<Card 
  title="需要授权" 
  className={`risk-${request.riskLevel}`}
>
  <Alert 
    message={`${request.toolName} 请求执行以下操作`}
    description={request.action}
    type={request.riskLevel === 'critical' ? 'error' : 'warning'}
  />
  
  {request.description && (
    <p>{request.description}</p>
  )}
  
  {request.details && (
    <Descriptions size="small">
      {Object.entries(request.details).map(([k, v]) => (
        <Descriptions.Item key={k} label={k}>{v}</Descriptions.Item>
      ))}
    </Descriptions>
  )}
  
  <Space>
    <Button type="primary" onClick={() => respond('allow')}>
      允许
    </Button>
    <Button danger onClick={() => respond('deny')}>
      拒绝
    </Button>
    {request.allowRemember && (
      <>
        <Button onClick={() => respond('allow_always')}>
          始终允许此工具
        </Button>
        <Button onClick={() => respond('deny_always')}>
          始终拒绝此工具
        </Button>
      </>
    )}
  </Space>
</Card>
```

### 响应格式

```json
{
  "request_id": "perm_12345678",
  "action": "allow",
  "remember": false
}
```

---

## 类型对比

| 特性 | Clarification | Decision | EnvVar | Permission |
|------|---------------|----------|--------|------------|
| 主要目的 | 澄清意图 | 做出选择 | 收集凭证 | 授权操作 |
| 允许自定义 | ✓ 默认允许 | ✗ 默认不允许 | - | - |
| 多选支持 | ✗ | ✓ 可配置 | - | - |
| 风险等级 | - | ✓ 每个选项 | - | ✓ 整体 |
| 记住选择 | - | - | ✓ 保存凭证 | ✓ 记住授权 |
| 典型超时 | 300s | 300s | 300s | 60s |
| 默认值 | ✓ | ✓ | ✓ | ✓ |

## 工具集成

在 Agent 工具中使用 HITL：

```python
from src.infrastructure.agent.tools.base import BaseTool

class FileDeleteTool(BaseTool):
    async def execute(self, path: str):
        # 请求权限
        permission = await self.hitl_handler.request_permission(
            tool_name="file_delete",
            action=f"删除文件: {path}",
            risk_level=RiskLevel.HIGH,
        )
        
        if permission in (PermissionAction.DENY, PermissionAction.DENY_ALWAYS):
            return {"error": "用户拒绝删除操作"}
        
        # 执行删除
        os.remove(path)
        return {"success": True}
```
