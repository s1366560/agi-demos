# ReActAgent 文件上传功能 - 技术设计文档

> 创建日期: 2026-02-01  
> 作者: AI Assistant  
> 状态: 实现中

## 1. 概述

为ReActAgent增加文件上传功能，允许用户在对话中上传图片、文档等附件，支持两种使用场景：

1. **LLM多模态理解** - 图片/文档发送给LLM分析（如图片识别、文档分析）
2. **沙箱文件访问** - 文件上传到沙箱供工具执行（如代码运行、数据处理）

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (React)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  InputBar.tsx                                                               │
│  ├── FileUploader (新组件)                                                   │
│  │   ├── 文件选择 (拖拽/点击)                                                 │
│  │   ├── Purpose选择 (llm_context / sandbox_input / both)                   │
│  │   ├── 分片上传进度                                                        │
│  │   └── 附件预览/删除                                                       │
│  └── 消息发送 (带attachment_ids)                                             │
└─────────────────┬───────────────────────────────────────────────────────────┘
                  │ HTTP POST /api/v1/attachments/upload
                  │ (multipart/form-data 或 分片上传)
                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Backend API (FastAPI)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  attachments.py (新Router)                                                  │
│  ├── POST /upload/initiate    - 初始化分片上传                               │
│  ├── POST /upload/part        - 上传单个分片                                 │
│  ├── POST /upload/complete    - 完成分片上传                                 │
│  ├── POST /upload/simple      - 小文件直接上传 (≤10MB)                       │
│  ├── GET /{id}/download       - 下载附件                                     │
│  └── DELETE /{id}             - 删除附件                                     │
└─────────────────┬───────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│               AttachmentService (新Application Service)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  ├── initiate_multipart_upload()   - 初始化S3分片上传                        │
│  ├── upload_part()                  - 上传分片到S3                           │
│  ├── complete_multipart_upload()    - 完成分片上传                           │
│  ├── upload_simple()                - 小文件直接上传                         │
│  ├── prepare_for_llm()              - 获取base64用于LLM                      │
│  └── prepare_for_sandbox()          - 获取内容用于沙箱导入                    │
└─────────────────┬───────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              StorageServicePort (抽象接口 - 已存在，需扩展)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  新增方法:                                                                   │
│  ├── create_multipart_upload()      - 创建分片上传                           │
│  ├── upload_part()                   - 上传单个分片                          │
│  ├── complete_multipart_upload()     - 完成分片上传                          │
│  ├── abort_multipart_upload()        - 取消分片上传                          │
│  └── generate_presigned_upload_url() - 生成上传预签名URL                     │
└─────────────────┬───────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              S3StorageAdapter (实现 - 已存在，需扩展)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  使用 aioboto3 实现分片上传方法                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 3. 领域模型设计

### 3.1 Attachment 值对象

```python
# src/domain/model/agent/attachment.py

class AttachmentPurpose(str, Enum):
    """附件用途."""
    LLM_CONTEXT = "llm_context"      # 发送给LLM进行多模态理解
    SANDBOX_INPUT = "sandbox_input"  # 上传到沙箱供工具使用
    BOTH = "both"                    # 两者都需要

class AttachmentStatus(str, Enum):
    """附件状态."""
    PENDING = "pending"              # 分片上传中
    UPLOADED = "uploaded"            # 上传完成
    PROCESSING = "processing"        # 处理中 (如导入沙箱)
    READY = "ready"                  # 就绪可用
    FAILED = "failed"                # 失败
    EXPIRED = "expired"              # 已过期

@dataclass(kw_only=True)
class Attachment:
    """对话附件实体."""
    id: str
    conversation_id: str
    project_id: str
    tenant_id: str
    
    # 文件信息
    filename: str
    mime_type: str
    size_bytes: int
    object_key: str
    
    # 用途和状态
    purpose: AttachmentPurpose
    status: AttachmentStatus = AttachmentStatus.PENDING
    
    # 分片上传信息
    upload_id: Optional[str] = None
    total_parts: Optional[int] = None
    uploaded_parts: int = 0
    
    # 沙箱相关
    sandbox_path: Optional[str] = None
    
    # 时间戳
    created_at: datetime
    expires_at: Optional[datetime] = None
```

### 3.2 Message 扩展

```python
# 在 Message 模型中添加
attachment_ids: list[str] = field(default_factory=list)
```

## 4. 存储层设计

### 4.1 StorageServicePort 扩展

新增方法支持S3分片上传：

- `create_multipart_upload()` - 初始化分片上传
- `upload_part()` - 上传单个分片
- `complete_multipart_upload()` - 完成分片上传
- `abort_multipart_upload()` - 取消分片上传
- `generate_presigned_upload_url()` - 生成上传预签名URL

### 4.2 分片大小

- 最小分片: 5MB (S3要求)
- 建议分片: 5MB
- 最大文件: 100MB (沙箱输入) / 10MB (LLM上下文)

## 5. API 设计

### 5.1 初始化分片上传

```
POST /api/v1/attachments/upload/initiate

Request:
{
    "conversation_id": "string",
    "project_id": "string",
    "filename": "string",
    "mime_type": "string",
    "size_bytes": number,
    "purpose": "llm_context" | "sandbox_input" | "both"
}

Response:
{
    "attachment_id": "string",
    "upload_id": "string",
    "total_parts": number,
    "part_size": number
}
```

### 5.2 上传分片

```
POST /api/v1/attachments/upload/part

Form Data:
- attachment_id: string
- part_number: number
- file: binary

Response:
{
    "part_number": number,
    "etag": "string"
}
```

### 5.3 完成上传

```
POST /api/v1/attachments/upload/complete

Request:
{
    "attachment_id": "string",
    "parts": [{"part_number": number, "etag": "string"}, ...]
}

Response:
{
    "id": "string",
    "filename": "string",
    "mime_type": "string",
    "size_bytes": number,
    "purpose": "string",
    "status": "string"
}
```

### 5.4 简单上传 (≤10MB)

```
POST /api/v1/attachments/upload/simple

Form Data:
- conversation_id: string
- project_id: string
- purpose: string
- file: binary

Response: AttachmentResponse
```

## 6. 沙箱集成

### 6.1 import_file MCP工具

新增工具用于将文件导入沙箱工作空间：

```python
async def import_file(
    filename: str,
    content_base64: str,
    destination: str = "/workspace/input",
) -> Dict[str, Any]:
    """将base64编码的文件写入沙箱."""
```

### 6.2 导入流程

1. 用户上传文件，purpose 包含 `sandbox_input`
2. 消息处理时检测到附件需要导入沙箱
3. 调用 `prepare_for_sandbox()` 获取 base64 内容
4. 自动调用 `import_file` 工具导入到 `/workspace/input/`
5. 后续工具可以访问该文件

## 7. LLM 多模态集成

### 7.1 消息格式

图片附件转换为多模态消息格式：

```python
{
    "type": "image_url",
    "image_url": {
        "url": "data:image/png;base64,{base64_content}",
        "detail": "auto"
    }
}
```

### 7.2 支持的格式

- 图片: `image/*` (PNG, JPEG, GIF, WebP)
- 文档: `application/pdf`, `text/*`

## 8. 文件限制

| 用途 | 最大大小 | 允许类型 |
|------|----------|----------|
| LLM Context | 10MB | image/*, application/pdf, text/* |
| Sandbox Input | 100MB | 所有类型 |

## 9. 数据库设计

### 9.1 attachments 表

```sql
CREATE TABLE attachments (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    
    filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL,
    object_key VARCHAR(500) NOT NULL,
    
    purpose VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    
    upload_id VARCHAR(200),
    total_parts INTEGER,
    uploaded_parts INTEGER DEFAULT 0,
    
    sandbox_path VARCHAR(500),
    metadata JSONB,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP,
    
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX ix_attachments_conversation_id ON attachments(conversation_id);
CREATE INDEX ix_attachments_status ON attachments(status);
CREATE INDEX ix_attachments_expires_at ON attachments(expires_at);
```

## 10. 前端设计

### 10.1 FileUploader 组件

- 文件选择（点击/拖拽）
- Purpose 选择下拉框
- 上传进度显示
- 附件预览和删除

### 10.2 集成到 InputBar

- 附件按钮点击触发文件选择
- 附件列表显示在输入框上方
- 发送消息时携带 attachment_ids

## 11. 实现顺序

1. **Phase 1**: 存储层扩展 (StorageServicePort + S3StorageAdapter)
2. **Phase 2**: 领域模型 (Attachment 值对象)
3. **Phase 3**: 数据库迁移
4. **Phase 4**: Repository 实现
5. **Phase 5**: AttachmentService
6. **Phase 6**: API 端点
7. **Phase 7**: 沙箱 import_file 工具
8. **Phase 8**: 消息处理集成
9. **Phase 9-11**: 前端实现

## 12. 安全考虑

1. **文件类型验证**: 服务端验证 MIME 类型
2. **文件大小限制**: 按用途限制最大大小
3. **路径遍历防护**: 沙箱导入时验证目标路径
4. **过期清理**: 24小时后自动清理未完成上传
5. **权限检查**: 验证用户对conversation/project的访问权限
