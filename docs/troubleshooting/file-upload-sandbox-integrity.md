# 文件上传到 Sandbox 完整性问题分析与解决方案

## 问题描述

用户报告：上传的文件（如 Excel、PDF）在 sandbox 中会出现文件结构被破坏的情况。

## 深度分析

### 测试结果

通过端到端测试脚本验证，**后端的整个数据链路是完整的**：

1. ✅ S3 上传/下载 - 数据完整
2. ✅ Base64 编解码 - 数据完整  
3. ✅ JSON/WebSocket 传输 - 数据完整
4. ✅ 文件写入 - 数据完整

### 数据流程分析

```
前端 File 对象
    ↓ [FormData 上传]
API 接收 (FastAPI UploadFile)
    ↓ [bytes]
S3/MinIO 存储
    ↓ [bytes - 验证通过]
S3 下载 (get_file)
    ↓ [bytes]
Base64 编码 (prepare_for_sandbox)
    ↓ [string]
JSON-RPC WebSocket 传输
    ↓ [string - 验证通过]
Base64 解码 (import_file)
    ↓ [bytes]
文件写入 (write_bytes)
    ↓
Sandbox 文件系统
```

### 可能的问题点

根据分析，问题可能出现在以下环节：

1. **前端上传** - 浏览器读取或传输文件时
2. **WebSocket 连接不稳定** - 大文件传输中断
3. **Sandbox 同步未执行** - `_sync_files_to_sandbox` 从未被调用
4. **Sandbox 容器状态** - 容器已退出或端口冲突

## 解决方案

### 1. 添加端到端文件完整性验证

**文件**: `src/application/services/attachment_service.py`

在 `prepare_for_sandbox` 中计算源文件 MD5：

```python
import hashlib
content_md5 = hashlib.md5(content).hexdigest()
return {
    ...
    "source_md5": content_md5,  # 源文件 MD5
}
```

### 2. Sandbox 导入时验证

**文件**: `sandbox-mcp-server/src/tools/import_tools.py`

在 `import_file` 中：
- 解码后计算 MD5
- 写入后再次读取验证
- 返回 MD5 供调用方验证

```python
# 写入后验证
written_content = file_path.read_bytes()
written_md5 = hashlib.md5(written_content).hexdigest()

if written_md5 != content_md5:
    return {"success": False, "error": "File integrity check failed"}
```

### 3. 调用方端到端验证

**文件**: `src/infrastructure/agent/actor/execution.py`

在 `_sync_files_to_sandbox` 中比对 MD5：

```python
source_md5 = file_data.get("source_md5")
sandbox_md5 = response.get("md5")

if source_md5 == sandbox_md5:
    logger.info("✅ File integrity verified")
else:
    logger.error("❌ FILE INTEGRITY MISMATCH")
```

### 4. 诊断日志增强

添加了详细的诊断日志：

- 源文件信息（大小、MD5、文件头）
- Base64 编码后信息
- WebSocket 传输状态
- Sandbox 写入后验证结果

## 测试脚本

### 基础完整性测试

```bash
cd /path/to/vip-memory
uv run python scripts/test_file_integrity.py
```

### 端到端测试（包含 S3）

```bash
uv run python scripts/test_e2e_file_integrity.py
```

## 诊断步骤

如果问题仍然存在，按以下步骤诊断：

### 1. 检查日志

```bash
# 查看 attachment 相关日志
grep -a "AttachmentService\|prepare_for_sandbox\|source_md5" logs/agent-worker.log | tail -20

# 查看 sandbox 导入日志
grep -a "import_file\|Importing file\|integrity" logs/agent-worker.log | tail -20

# 查看 sandbox 容器日志
docker logs mcp-sandbox-xxx 2>&1 | tail -50
```

### 2. 验证 Sandbox 容器状态

```bash
# 检查容器状态
docker ps -a --filter "name=mcp-sandbox"

# 检查端口是否冲突
docker inspect mcp-sandbox-xxx | grep -A5 "Ports"
```

### 3. 检查数据库关联

```python
# 检查 project-sandbox 关联
async with async_session_factory() as db:
    repo = SqlAlchemyProjectSandboxRepository(db)
    assoc = await repo.find_by_project('your-project-id')
    print(f"Sandbox ID: {assoc.sandbox_id}")
```

### 4. 使用 curl 直接测试上传

```bash
# 直接上传文件到 API
curl -X POST http://localhost:8000/api/v1/attachments/upload/simple \
  -H "Authorization: Bearer $API_KEY" \
  -F "conversation_id=xxx" \
  -F "project_id=xxx" \
  -F "purpose=both" \
  -F "file=@/path/to/test.xlsx"
```

## 预期日志输出

正确工作时，应该看到类似日志：

```
[AttachmentService] prepare_for_sandbox: filename=test.xlsx, size=108636, md5=abc123..., header=504b0304...
[AgentSession] Prepared attachment xxx for sandbox: filename=test.xlsx, db_size=108636, base64_len=144848, estimated_decoded=108636, content_hash=def456
[AgentSession] _sync_files_to_sandbox called with 1 files for project=xxx
[AgentSession] Importing file to sandbox: test.xlsx (~108636 bytes, base64_len=144848)
[import_file] Decoded content: size=108636, md5=abc123..., header=504b0304...
[import_file] Successfully imported: /workspace/test.xlsx (108636 bytes, md5=abc123...)
[AgentSession] ✅ File integrity verified: test.xlsx (source_md5=abc123... == sandbox_md5=abc123...)
[AgentSession] Successfully imported test.xlsx: path=/workspace/test.xlsx, size=108636 bytes, md5=abc123...
```

## 文件修改清单

1. `src/application/services/attachment_service.py`
   - `prepare_for_sandbox()` 添加 MD5 计算和日志

2. `sandbox-mcp-server/src/tools/import_tools.py`
   - `import_file()` 添加完整性验证

3. `src/infrastructure/agent/actor/execution.py`
   - `_prepare_attachments()` 添加 base64 验证日志
   - `_sync_files_to_sandbox()` 添加端到端 MD5 验证
   - 修复 `SqlAlchemyProjectSandboxRepository` 类名和方法名

4. 新增测试脚本：
   - `scripts/test_file_integrity.py` - 基础完整性测试
   - `scripts/test_e2e_file_integrity.py` - 端到端测试
