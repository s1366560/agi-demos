# 修复计划: export_artifact 导出文件在历史消息中无法打开

## 问题描述

用户报告两个问题：
1. 使用 `export_artifact` 工具导出的文件，在历史消息（刷新页面后）渲染时无法打开导出的文件
2. 点击"在 Canvas 中打开"按钮时，无法正常渲染内容

## 根因分析

### 问题 1: Presigned URL 过期

**位置**: `src/application/services/artifact_service.py:64`

```python
url_expiration_seconds: int = 7 * 24 * 3600,  # 7 days default
```

导出文件的 URL 是 MinIO/S3 的 **presigned URL**，默认有效期 7 天。超过这个时间后，URL 失效，文件无法访问。

### 问题 2: Canvas 打开不加载内容（主要问题）

**对比两个组件的 `handleOpenInCanvas` 实现：**

**TimelineEventItem.tsx:769-812** (正确实现):
```tsx
const handleOpenInCanvas = useCallback(async () => {
  const url = artifactUrl || artifactPreviewUrl;
  if (!url) return;

  try {
    const response = await fetch(url);        // ← 从 URL 加载内容
    const content = await response.text();    // ← 转换为文本

    useCanvasStore.getState().openTab({
      id: event.artifactId,
      title: event.filename,
      type: contentType,
      content,                                // ← 使用加载的内容
      ...
    });
  } catch { ... }
}, [...]);
```

**MessageBubble.tsx:723-736** (问题实现):
```tsx
const handleOpenInCanvas = () => {
  const ext = event.filename.split('.').pop() || '';
  const type = ...;
  canvasOpenTab({
    id: event.artifactId,
    title: event.filename,
    type,
    content: t('agent.canvas.loadingContent', 'Loading content...'),  // ← 硬编码占位符！
    language: ext,
  });
  setLayoutMode('canvas');
};
```

**问题**: `MessageBubble.tsx` 没有从 URL 加载内容，只是显示 "Loading content..." 占位符。

## 实现计划

### Phase 1: 修复 MessageBubble 的 Canvas 打开逻辑（优先级高）✅ 已完成

**文件**: `web/src/components/agent/messageBubble/MessageBubble.tsx:723-753`

已将 `handleOpenInCanvas` 改为异步函数，从 URL 加载内容：

```tsx
const handleOpenInCanvas = async () => {
  const url = artifactUrl || artifactPreviewUrl;
  if (!url) return;

  try {
    // Fetch content from the artifact URL
    const response = await fetch(url);
    const content = await response.text();

    // Determine canvas content type from artifact category
    const typeMap: Record<string, 'code' | 'markdown' | 'data'> = {
      code: 'code',
      document: 'markdown',
      data: 'data',
    };
    const contentType = typeMap[event.category] || 'code';
    const ext = event.filename.split('.').pop()?.toLowerCase();

    canvasOpenTab({
      id: event.artifactId,
      title: event.filename,
      type: contentType,
      content,
      language: ext,
      artifactId: event.artifactId,
      artifactUrl: url,
    });
    setLayoutMode('canvas');
  } catch {
    // Silently fail - user can still download the file directly
  }
};
```

### Phase 2: 后端 URL 刷新 API（已确认存在）

**文件**: `src/infrastructure/adapters/primary/web/routers/artifacts.py:244-270`

API 端点: `POST /api/v1/artifacts/{artifact_id}/refresh-url`

### Phase 3: 前端 Service（已确认存在）

**文件**: `web/src/services/artifactService.ts:96-101`

### Phase 4: 添加 URL 刷新机制（处理过期 URL）✅ 已完成

**文件**: `web/src/components/agent/messageBubble/MessageBubble.tsx`

修改 `ArtifactCreated` 组件，添加 URL 刷新功能：

1. **添加状态管理**
   ```tsx
   const [refreshingUrl, setRefreshingUrl] = useState(false);
   const [refreshError, setRefreshError] = useState<string | null>(null);
   const [currentUrl, setCurrentUrl] = useState<string | null>(null);
   ```

2. **实现刷新函数**
   ```tsx
   const handleRefreshUrl = async () => {
     setRefreshingUrl(true);
     setRefreshError(null);
     try {
       const newUrl = await artifactService.refreshUrl(event.artifactId);
       setCurrentUrl(newUrl);
       setImageError(false);
       setImageLoaded(false);
     } catch (err) {
       setRefreshError(getErrorMessage(err));
     } finally {
       setRefreshingUrl(false);
     }
   };
   ```

3. **修改 URL 优先级**
   ```tsx
   // Priority: refreshed URL > store URL > event URL
   const artifactUrl = currentUrl || storeArtifact?.url || event.url;
   ```

4. **添加刷新按钮 UI**
   - 图片加载失败时显示错误提示和刷新按钮
   - 文件信息区域也显示刷新按钮（当 URL 失效时）

### Phase 5: 可选改进 - 自动刷新

首次 URL 加载失败时自动尝试刷新（一次）。- 可后续添加

## 相关文件

| 文件 | 用途 | 修改 |
|------|------|------|
| `web/src/components/agent/messageBubble/MessageBubble.tsx` | 前端渲染组件 | **需修改** |
| `web/src/components/agent/TimelineEventItem.tsx` | 参考实现 | 无需修改 |
| `web/src/services/artifactService.ts` | Artifact 服务 | 已存在 |
| `web/src/stores/canvasStore.ts` | Canvas 状态 | 无需修改 |
| `src/infrastructure/adapters/primary/web/routers/artifacts.py` | 后端 API | 已存在 |

## 修复优先级

1. **高优先级**: Phase 1 - 修复 Canvas 打开不加载内容（这是主要 bug）
2. **中优先级**: Phase 4 - URL 刷新机制（处理过期 URL）

## 风险评估

| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| Canvas 打开失败 | 低 | 复用 TimelineEventItem 的已验证实现 |
| 后端 artifact 是内存存储 | 低 | 刷新需要 artifact 仍在内存中 |
| URL fetch CORS 问题 | 低 | S3/MinIO presigned URL 允许跨域 |

## 预估复杂度: 低

- 后端: 无需修改
- 前端: 约 50 行代码修改（主要是复制 TimelineEventItem 的逻辑到 MessageBubble）
