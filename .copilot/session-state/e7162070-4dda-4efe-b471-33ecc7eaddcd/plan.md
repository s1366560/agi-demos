# Artifact + Canvas Architecture Analysis

## Current Architecture (How It Actually Works)

### The Complete Artifact Flow

```
┌─────────────────────────────────────────────────────────────┐
│  SANDBOX (Docker Container)                                  │
│  ┌─────────────────────────────────────┐                     │
│  │ sandbox-mcp-server (MCP Server)     │                     │
│  │ ├─ read_file tool (text, paginated) │                     │
│  │ └─ export_artifact tool             │                     │
│  │    - Reads file from /workspace     │                     │
│  │    - Base64 encodes binary files    │                     │
│  │    - Returns full content + metadata│                     │
│  └─────────────┬───────────────────────┘                     │
└────────────────┼────────────────────────────────────────────┘
                 │ MCP JSON-RPC (HTTP/SSE/WebSocket)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  BACKEND (Python)                                            │
│  ┌─────────────────────────────────────────┐                 │
│  │ SandboxMCPToolWrapper                   │                 │
│  │ - Receives full file content in result  │                 │
│  │ - Returns {content, artifact} dict      │                 │
│  └──────────────┬──────────────────────────┘                 │
│                 ▼                                             │
│  ┌─────────────────────────────────────────┐                 │
│  │ Processor._process_tool_artifacts()     │                 │
│  │ ① Decodes base64/utf-8 → bytes          │                 │
│  │ ② Emits artifact_created (no URL yet)   │                 │
│  │ ③ IF text < 500KB: emits artifact_open  │─── Canvas SSE   │
│  │    (includes full text content)          │                 │
│  │ ④ Background thread → S3/MinIO upload   │                 │
│  │ ⑤ Emits artifact_ready (presigned URL)  │                 │
│  └─────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
                 │ SSE Events
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND (React)                                            │
│                                                              │
│  artifact_created → ArtifactCreatedItem (inline card)        │
│                     - Shows filename, size, category          │
│                     - No URL yet → "Uploading..."            │
│                                                              │
│  artifact_open   → canvasStore.openTab() → CanvasPanel       │
│                     - Content already in SSE event            │
│                     - Auto-switches to canvas layout          │
│                                                              │
│  artifact_ready  → sandboxStore updates URL                   │
│                     - Card shows "Download" link              │
│                     - "Open in Canvas" button appears         │
│                                                              │
│  User clicks "Open in Canvas" → fetch(presignedURL)          │
│                                → canvasStore.openTab()        │
└─────────────────────────────────────────────────────────────┘
```

### Key Insight: The Current System Already Works

The artifact flow is **already correct**:

1. **Auto-open (< 500KB text)**: Backend reads content from sandbox via MCP, 
   decodes it, emits `artifact_open` SSE with inline content → canvas opens 
   immediately. No URL fetch needed.

2. **Manual open (user clicks "Open in Canvas")**: After `artifact_ready` fires,
   the presigned S3/MinIO URL is available. Frontend fetches content from this URL
   and opens in canvas. This works because the file was uploaded to S3 in step ④.

3. **Download**: Same presigned URL.

### What's Already Implemented (This Session)

| Feature | Status | How It Works |
|---------|--------|--------------|
| Auto-open in canvas (text < 500KB) | Was working | `artifact_open` SSE → canvasStore |
| "Open in Canvas" button on artifact card | NEW | Fetches from presigned S3 URL |
| Canvas tabs link to artifact ID | NEW | `artifactId` + `artifactUrl` on CanvasTab |
| Save canvas edits back to S3 | NEW | `PUT /artifacts/{id}/content` |
| Code blocks "Open in Canvas" | NEW | CodeBlock component on all `<pre>` |
| New empty canvas tabs | NEW | Empty state + tab bar "+" button |

### Potential Issues & Edge Cases

#### 1. Presigned URL Expiration
- **Problem**: Presigned URLs expire (default 7 days). If user returns to an old 
  conversation, clicking "Open in Canvas" will fail.
- **Current mitigation**: `POST /artifacts/{id}/refresh-url` endpoint exists
- **Future**: The "Open in Canvas" handler should catch 403 errors and auto-refresh

#### 2. Large Files (> 500KB)
- **Problem**: Backend skips `artifact_open` for files > 500KB. User must click 
  "Open in Canvas" manually, which fetches from S3. This works but large files 
  in canvas could cause performance issues.
- **Current mitigation**: Only text-decodable categories show the button
- **Future**: Consider warning or truncating for very large files

#### 3. Binary Artifacts (images, PDFs)
- **Problem**: These can't be opened in a text canvas. The "Open in Canvas" button 
  correctly filters them out (`isCanvasCompatible` check).
- **Future**: Image preview tab, PDF viewer tab in canvas

#### 4. Sandbox Lifecycle
- **Problem**: Sandbox containers are ephemeral. Once destroyed, files are gone.
  But this is fine because files are uploaded to S3 before the sandbox is destroyed.
- **Non-issue**: S3 is the permanent store.

## Conclusion

**The architecture is sound. No changes needed.**

The "Open in Canvas" button fetches from S3 presigned URLs, not from the sandbox 
directly. The file content flows:

```
Sandbox filesystem → export_artifact (MCP) → Processor → S3 upload → Presigned URL
                                                        → artifact_open SSE (inline content)
```

Both paths (auto-open via SSE and manual open via URL fetch) provide content 
independently of the sandbox lifecycle.

## Previous Session Work (Completed)

- [x] Phase 1: Connect artifacts to canvas (Open in Canvas button, artifactId linkage, i18n)
- [x] Phase 2: User-initiated canvas (New tabs, code block actions)
- [x] Phase 3: Backend save endpoint (PUT /artifacts/{id}/content)
- [x] Phase 4: Verified (TypeScript + Python builds pass)
