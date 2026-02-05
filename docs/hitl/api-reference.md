# HITL API 参考

本文档详细描述 HITL (Human-in-the-Loop) 系统的 REST API 接口。

## 目录

- [API 概述](#api-概述)
- [认证](#认证)
- [端点列表](#端点列表)
- [错误处理](#错误处理)
- [事件格式](#事件格式)
- [示例代码](#示例代码)

---

## API 概述

### 基础 URL

```
http://localhost:8000/api/v1/agent/hitl
```

### 通用响应格式

所有 API 响应遵循统一格式：

```json
{
  "success": true,
  "data": { ... },
  "message": "Operation completed successfully"
}
```

错误响应：

```json
{
  "success": false,
  "error": {
    "code": "HITL_REQUEST_NOT_FOUND",
    "message": "HITL request not found",
    "details": { ... }
  }
}
```

---

## 认证

所有 HITL API 需要 Bearer Token 认证：

```bash
Authorization: Bearer ms_sk_xxx...
```

API Key 格式: `ms_sk_` + 64 个十六进制字符

---

## 端点列表

### 1. 获取待处理 HITL 请求

获取指定对话中待处理的 HITL 请求列表。

```
GET /hitl/conversations/{conversation_id}/pending
```

#### 请求参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| conversation_id | path | string | 是 | 对话 UUID |

#### 响应

```json
{
  "success": true,
  "data": {
    "pending_requests": [
      {
        "request_id": "clar_12345678",
        "type": "clarification",
        "status": "pending",
        "created_at": "2026-02-04T15:30:00Z",
        "expires_at": "2026-02-04T15:35:00Z",
        "request_data": {
          "question": "您想要执行什么操作？",
          "options": ["选项A", "选项B", "选项C"],
          "allow_custom": true
        }
      }
    ],
    "total": 1
  }
}
```

#### 示例

```bash
curl -X GET "http://localhost:8000/api/v1/agent/hitl/conversations/abc123/pending" \
  -H "Authorization: Bearer ms_sk_xxx"
```

---

### 2. 提交 HITL 响应

提交用户对 HITL 请求的响应。

```
POST /hitl/respond
```

#### 请求体

```json
{
  "request_id": "clar_12345678",
  "response": {
    "answer": "选项A"
  },
  "metadata": {
    "source": "web_ui",
    "user_agent": "Mozilla/5.0..."
  }
}
```

#### 请求字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| request_id | string | 是 | HITL 请求 ID |
| response | object | 是 | 响应数据 (根据类型不同) |
| metadata | object | 否 | 附加元数据 |

#### 响应

```json
{
  "success": true,
  "data": {
    "request_id": "clar_12345678",
    "status": "answered",
    "answered_at": "2026-02-04T15:31:00Z"
  },
  "message": "Response submitted successfully"
}
```

#### 错误响应

| 状态码 | 错误码 | 说明 |
|--------|--------|------|
| 400 | INVALID_REQUEST | 请求格式无效 |
| 400 | REQUEST_NOT_PENDING | 请求已不在待处理状态 |
| 404 | REQUEST_NOT_FOUND | 找不到指定的 HITL 请求 |
| 409 | REQUEST_EXPIRED | 请求已超时 |
| 500 | WORKFLOW_ERROR | 工作流通信失败 |

#### 示例

```bash
# 澄清请求响应
curl -X POST "http://localhost:8000/api/v1/agent/hitl/respond" \
  -H "Authorization: Bearer ms_sk_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "clar_12345678",
    "response": {
      "answer": "我想要删除这个文件"
    }
  }'

# 决策请求响应
curl -X POST "http://localhost:8000/api/v1/agent/hitl/respond" \
  -H "Authorization: Bearer ms_sk_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "deci_87654321",
    "response": {
      "decision": "proceed",
      "reason": "已确认风险，继续执行"
    }
  }'

# 环境变量请求响应
curl -X POST "http://localhost:8000/api/v1/agent/hitl/respond" \
  -H "Authorization: Bearer ms_sk_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "envv_11111111",
    "response": {
      "values": {
        "OPENAI_API_KEY": "sk-xxx",
        "DATABASE_URL": "postgres://..."
      },
      "save": true
    }
  }'

# 权限请求响应
curl -X POST "http://localhost:8000/api/v1/agent/hitl/respond" \
  -H "Authorization: Bearer ms_sk_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "perm_22222222",
    "response": {
      "granted": true,
      "remember": true,
      "duration": "session"
    }
  }'
```

---

### 3. 取消 HITL 请求

取消一个待处理的 HITL 请求。

```
POST /hitl/cancel
```

#### 请求体

```json
{
  "request_id": "clar_12345678",
  "reason": "用户主动取消"
}
```

#### 响应

```json
{
  "success": true,
  "data": {
    "request_id": "clar_12345678",
    "status": "cancelled",
    "cancelled_at": "2026-02-04T15:32:00Z"
  }
}
```

#### 示例

```bash
curl -X POST "http://localhost:8000/api/v1/agent/hitl/cancel" \
  -H "Authorization: Bearer ms_sk_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "clar_12345678",
    "reason": "不再需要"
  }'
```

---

### 4. 获取 HITL 请求详情

获取单个 HITL 请求的详细信息。

```
GET /hitl/requests/{request_id}
```

#### 响应

```json
{
  "success": true,
  "data": {
    "request_id": "clar_12345678",
    "type": "clarification",
    "status": "answered",
    "conversation_id": "abc123",
    "message_id": "msg456",
    "request_data": {
      "question": "您想要执行什么操作？",
      "options": ["选项A", "选项B"],
      "allow_custom": true
    },
    "response": {
      "answer": "选项A"
    },
    "created_at": "2026-02-04T15:30:00Z",
    "answered_at": "2026-02-04T15:31:00Z",
    "timeout_seconds": 300
  }
}
```

---

## 错误处理

### 错误码列表

| 错误码 | HTTP 状态 | 说明 |
|--------|-----------|------|
| `HITL_REQUEST_NOT_FOUND` | 404 | 找不到 HITL 请求 |
| `HITL_REQUEST_NOT_PENDING` | 400 | 请求不在待处理状态 |
| `HITL_REQUEST_EXPIRED` | 409 | 请求已超时 |
| `HITL_INVALID_RESPONSE` | 400 | 响应格式无效 |
| `HITL_ACTOR_ERROR` | 500 | Ray actor resume failed |
| `HITL_UNAUTHORIZED` | 401 | 未授权访问 |
| `HITL_FORBIDDEN` | 403 | 无权限操作此请求 |

### 错误响应示例

```json
{
  "success": false,
  "error": {
    "code": "HITL_REQUEST_NOT_PENDING",
    "message": "HITL request is not in pending status",
    "details": {
      "request_id": "clar_12345678",
      "current_status": "answered"
    }
  }
}
```

---

## 事件格式

### SSE 事件

HITL 系统通过 Server-Sent Events (SSE) 推送实时事件。

#### 连接

```javascript
const eventSource = new EventSource(
  `http://localhost:8000/api/v1/agent/stream?conversation_id=${conversationId}`
);
```

#### 事件类型

| 事件类型 | 说明 |
|----------|------|
| `clarification_asked` | 澄清请求发起 |
| `clarification_answered` | 澄清请求已回答 |
| `decision_asked` | 决策请求发起 |
| `decision_answered` | 决策请求已回答 |
| `env_var_requested` | 环境变量请求发起 |
| `env_var_provided` | 环境变量已提供 |
| `permission_asked` | 权限请求发起 |
| `permission_replied` | 权限请求已回复 |

#### 事件数据结构

```typescript
// clarification_asked
{
  type: "clarification_asked",
  request_id: "clar_12345678",
  conversation_id: "abc123",
  data: {
    question: "您想要执行什么操作？",
    options: ["选项A", "选项B"],
    allow_custom: true,
    default_answer: null,
    timeout_seconds: 300
  }
}

// decision_asked
{
  type: "decision_asked",
  request_id: "deci_12345678",
  conversation_id: "abc123",
  data: {
    decision_type: "high_risk_operation",
    title: "确认删除操作",
    description: "此操作将永久删除数据",
    options: [
      { key: "proceed", label: "继续", style: "danger" },
      { key: "cancel", label: "取消", style: "default" }
    ],
    risks: ["数据丢失", "不可恢复"],
    timeout_seconds: 300
  }
}

// env_var_requested
{
  type: "env_var_requested",
  request_id: "envv_12345678",
  conversation_id: "abc123",
  data: {
    fields: [
      {
        name: "OPENAI_API_KEY",
        label: "OpenAI API Key",
        required: true,
        sensitive: true,
        description: "用于调用 OpenAI API"
      }
    ],
    allow_save: true,
    timeout_seconds: 300
  }
}

// permission_asked
{
  type: "permission_asked",
  request_id: "perm_12345678",
  conversation_id: "abc123",
  data: {
    tool_name: "file_delete",
    tool_display_name: "删除文件",
    action: "delete /path/to/file.txt",
    risk_level: "high",
    description: "Agent 请求删除指定文件",
    allow_remember: true,
    timeout_seconds: 300
  }
}
```

---

## 响应数据结构

### 不同类型的响应格式

#### Clarification 响应

```json
{
  "answer": "用户的回答文本",
  // 或从选项中选择
  "selected_option": "选项A"
}
```

#### Decision 响应

```json
{
  "decision": "proceed",  // 或 "cancel", 或自定义选项 key
  "reason": "用户提供的理由 (可选)"
}
```

#### EnvVar 响应

```json
{
  "values": {
    "OPENAI_API_KEY": "sk-xxx",
    "DATABASE_URL": "postgres://..."
  },
  "save": true  // 是否保存到项目配置
}
```

#### Permission 响应

```json
{
  "granted": true,           // 是否授权
  "remember": true,          // 是否记住选择
  "duration": "session",     // "once" | "session" | "forever"
  "scope": "this_tool"       // "this_action" | "this_tool" | "all_tools"
}
```

---

## 示例代码

### Python 客户端

```python
import httpx
import asyncio

API_KEY = "ms_sk_xxx"
BASE_URL = "http://localhost:8000/api/v1/agent/hitl"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

async def get_pending_requests(conversation_id: str):
    """获取待处理的 HITL 请求"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/conversations/{conversation_id}/pending",
            headers=headers
        )
        return response.json()

async def submit_response(request_id: str, response_data: dict):
    """提交 HITL 响应"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/respond",
            headers=headers,
            json={
                "request_id": request_id,
                "response": response_data
            }
        )
        return response.json()

# 使用示例
async def main():
    # 获取待处理请求
    pending = await get_pending_requests("conv-123")
    print(f"Pending requests: {pending}")
    
    if pending["data"]["pending_requests"]:
        request = pending["data"]["pending_requests"][0]
        
        # 提交响应
        result = await submit_response(
            request["request_id"],
            {"answer": "选项A"}
        )
        print(f"Response submitted: {result}")

asyncio.run(main())
```

### TypeScript 客户端

```typescript
import axios from 'axios';

const API_KEY = 'ms_sk_xxx';
const BASE_URL = 'http://localhost:8000/api/v1/agent/hitl';

const client = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Authorization': `Bearer ${API_KEY}`,
    'Content-Type': 'application/json'
  }
});

// 获取待处理请求
async function getPendingRequests(conversationId: string) {
  const response = await client.get(`/conversations/${conversationId}/pending`);
  return response.data;
}

// 提交响应
async function submitResponse(requestId: string, responseData: object) {
  const response = await client.post('/respond', {
    request_id: requestId,
    response: responseData
  });
  return response.data;
}

// SSE 监听
function subscribeToEvents(conversationId: string) {
  const eventSource = new EventSource(
    `http://localhost:8000/api/v1/agent/stream?conversation_id=${conversationId}`
  );

  eventSource.addEventListener('clarification_asked', (event) => {
    const data = JSON.parse(event.data);
    console.log('Clarification requested:', data);
    // 处理澄清请求
  });

  eventSource.addEventListener('decision_asked', (event) => {
    const data = JSON.parse(event.data);
    console.log('Decision requested:', data);
    // 处理决策请求
  });

  return eventSource;
}
```

---

## WebSocket 协议 (可选)

除了 SSE，也支持 WebSocket 连接：

### 连接

```
ws://localhost:8000/api/v1/agent/ws?conversation_id=xxx
```

### 消息格式

```json
// 订阅
{
  "type": "subscribe",
  "conversation_id": "abc123"
}

// HITL 事件
{
  "type": "hitl_event",
  "event_type": "clarification_asked",
  "data": { ... }
}

// 提交响应
{
  "type": "hitl_respond",
  "request_id": "clar_12345678",
  "response": { "answer": "选项A" }
}
```

---

## 相关链接

- [HITL 架构设计](./architecture.md)
- [请求类型详解](./request-types.md)
- [前端集成指南](./frontend-guide.md)
- [故障排除指南](./troubleshooting.md)
