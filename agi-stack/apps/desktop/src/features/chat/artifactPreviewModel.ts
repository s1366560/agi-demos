export type ArtifactPreviewInput = {
  artifactId: string;
  mimeType: string;
  sizeBytes: number;
  integrity: 'ready' | 'corrupt';
  maxPreviewBytes?: number;
};

export type ArtifactPreviewFallbackReason =
  | 'invalid_metadata'
  | 'corrupt_content'
  | 'preview_size_limit'
  | 'office_preview_unavailable'
  | 'unsupported_mime';

type SandboxedIframeIsolation = {
  kind: 'sandboxed_iframe';
  sandboxTokens: readonly string[];
  allowScripts: false;
  allowForms: false;
  allowNavigation: false;
};

export type ArtifactPreviewPlan =
  | {
      kind: 'preview';
      renderer:
        | 'html_iframe'
        | 'pdf_iframe'
        | 'image'
        | 'audio'
        | 'video'
        | 'sanitized_svg'
        | 'docx'
        | 'xlsx';
      mimeType: string;
      byteSource: 'authenticated_artifact_api';
      objectUrl: 'required' | 'forbidden';
      isolation:
        | SandboxedIframeIsolation
        | { kind: 'blob_iframe' }
        | { kind: 'element' }
        | { kind: 'sanitized_dom' }
        | { kind: 'sanitized_table'; sheetTabs: true };
      transform: 'none' | 'sanitize_svg' | 'docx_preview' | 'sheetjs';
    }
  | {
      kind: 'download';
      mimeType: string;
      reason: ArtifactPreviewFallbackReason;
    };

export type ArtifactPreviewCleanupCommand =
  | { type: 'abort_request'; requestId: number }
  | { type: 'revoke_object_url'; url: string };

export type ArtifactPreviewLifecycleActive = {
  requestId: number;
  artifactId: string;
  scopeKey: string;
  phase: 'loading' | 'ready' | 'failed';
  objectUrl: string | null;
  failureReason: string | null;
};

export type ArtifactPreviewLifecycleState = {
  nextRequestId: number;
  active: ArtifactPreviewLifecycleActive | null;
};

export type ArtifactPreviewLoadRequest = {
  requestId: number;
  artifactId: string;
  scopeKey: string;
};

export type ArtifactPreviewLifecycleTransition = {
  state: ArtifactPreviewLifecycleState;
  commands: ArtifactPreviewCleanupCommand[];
};

const DEFAULT_MAX_PREVIEW_BYTES = 25 * 1024 * 1024;
const EMPTY_SANDBOX_TOKENS: readonly string[] = Object.freeze([]);

const IMAGE_MIME_TYPES: readonly string[] = Object.freeze([
  'image/avif',
  'image/bmp',
  'image/gif',
  'image/jpeg',
  'image/png',
  'image/webp',
]);

const AUDIO_MIME_TYPES: readonly string[] = Object.freeze([
  'audio/mp4',
  'audio/mpeg',
  'audio/ogg',
  'audio/wav',
  'audio/webm',
]);

const VIDEO_MIME_TYPES: readonly string[] = Object.freeze([
  'video/mp4',
  'video/quicktime',
  'video/webm',
  'video/x-matroska',
  'video/x-msvideo',
]);

const OFFICE_DOWNLOAD_MIME_TYPES: readonly string[] = Object.freeze([
  'application/msword',
  'application/vnd.ms-excel',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
]);

const DOCX_MIME_TYPE =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const XLSX_MIME_TYPE =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

export function planArtifactPreview(input: ArtifactPreviewInput): ArtifactPreviewPlan {
  const mimeType = normalizeMime(input.mimeType);
  const maxPreviewBytes = input.maxPreviewBytes ?? DEFAULT_MAX_PREVIEW_BYTES;
  if (
    !identifier(input.artifactId) ||
    !mimeType ||
    !isByteCount(input.sizeBytes) ||
    !isByteCount(maxPreviewBytes) ||
    maxPreviewBytes === 0
  ) {
    return downloadPlan(mimeType, 'invalid_metadata');
  }
  if (input.integrity !== 'ready') {
    return downloadPlan(mimeType, 'corrupt_content');
  }
  if (input.sizeBytes > maxPreviewBytes) {
    return downloadPlan(mimeType, 'preview_size_limit');
  }
  if (OFFICE_DOWNLOAD_MIME_TYPES.includes(mimeType)) {
    return downloadPlan(mimeType, 'office_preview_unavailable');
  }
  if (mimeType === 'text/html') {
    return blobPreviewPlan('html_iframe', mimeType, sandboxedIframeIsolation(), 'none');
  }
  if (mimeType === 'application/pdf') {
    return blobPreviewPlan('pdf_iframe', mimeType, { kind: 'blob_iframe' }, 'none');
  }
  if (mimeType === 'image/svg+xml') {
    return blobPreviewPlan(
      'sanitized_svg',
      mimeType,
      sandboxedIframeIsolation(),
      'sanitize_svg',
    );
  }
  if (IMAGE_MIME_TYPES.includes(mimeType)) {
    return blobPreviewPlan('image', mimeType, { kind: 'element' }, 'none');
  }
  if (AUDIO_MIME_TYPES.includes(mimeType)) {
    return blobPreviewPlan('audio', mimeType, { kind: 'element' }, 'none');
  }
  if (VIDEO_MIME_TYPES.includes(mimeType)) {
    return blobPreviewPlan('video', mimeType, { kind: 'element' }, 'none');
  }
  if (mimeType === DOCX_MIME_TYPE) {
    return {
      kind: 'preview',
      renderer: 'docx',
      mimeType,
      byteSource: 'authenticated_artifact_api',
      objectUrl: 'forbidden',
      isolation: { kind: 'sanitized_dom' },
      transform: 'docx_preview',
    };
  }
  if (mimeType === XLSX_MIME_TYPE) {
    return {
      kind: 'preview',
      renderer: 'xlsx',
      mimeType,
      byteSource: 'authenticated_artifact_api',
      objectUrl: 'forbidden',
      isolation: { kind: 'sanitized_table', sheetTabs: true },
      transform: 'sheetjs',
    };
  }
  return downloadPlan(mimeType, 'unsupported_mime');
}

export function emptyArtifactPreviewLifecycle(): ArtifactPreviewLifecycleState {
  return { nextRequestId: 1, active: null };
}

export function beginArtifactPreviewLoad(
  state: ArtifactPreviewLifecycleState,
  input: { artifactId: string; scopeKey: string },
): ArtifactPreviewLifecycleTransition & { request: ArtifactPreviewLoadRequest } {
  const request: ArtifactPreviewLoadRequest = {
    requestId: state.nextRequestId,
    artifactId: input.artifactId,
    scopeKey: input.scopeKey,
  };
  return {
    state: {
      nextRequestId: state.nextRequestId + 1,
      active: {
        ...request,
        phase: 'loading',
        objectUrl: null,
        failureReason: null,
      },
    },
    request,
    commands: cleanupCommands(state.active),
  };
}

export function completeArtifactPreviewLoad(
  state: ArtifactPreviewLifecycleState,
  requestId: number,
  objectUrl: string | null,
): ArtifactPreviewLifecycleTransition {
  if (state.active?.requestId !== requestId || state.active.phase !== 'loading') {
    return {
      state,
      commands: isBlobObjectUrl(objectUrl)
        ? [{ type: 'revoke_object_url', url: objectUrl }]
        : [],
    };
  }
  if (objectUrl !== null && !isBlobObjectUrl(objectUrl)) {
    return {
      state: {
        ...state,
        active: {
          ...state.active,
          phase: 'failed',
          objectUrl: null,
          failureReason: 'invalid_object_url',
        },
      },
      commands: [],
    };
  }
  return {
    state: {
      ...state,
      active: {
        ...state.active,
        phase: 'ready',
        objectUrl,
        failureReason: null,
      },
    },
    commands: [],
  };
}

export function failArtifactPreviewLoad(
  state: ArtifactPreviewLifecycleState,
  requestId: number,
  reason: string,
): ArtifactPreviewLifecycleTransition {
  if (state.active?.requestId !== requestId || state.active.phase !== 'loading') {
    return { state, commands: [] };
  }
  return {
    state: {
      ...state,
      active: {
        ...state.active,
        phase: 'failed',
        objectUrl: null,
        failureReason: reason,
      },
    },
    commands: [],
  };
}

export function disposeArtifactPreview(
  state: ArtifactPreviewLifecycleState,
): ArtifactPreviewLifecycleTransition {
  if (!state.active) return { state, commands: [] };
  return {
    state: { ...state, active: null },
    commands: cleanupCommands(state.active),
  };
}

function blobPreviewPlan(
  renderer: 'html_iframe' | 'pdf_iframe' | 'image' | 'audio' | 'video' | 'sanitized_svg',
  mimeType: string,
  isolation: SandboxedIframeIsolation | { kind: 'blob_iframe' } | { kind: 'element' },
  transform: 'none' | 'sanitize_svg',
): ArtifactPreviewPlan {
  return {
    kind: 'preview',
    renderer,
    mimeType,
    byteSource: 'authenticated_artifact_api',
    objectUrl: 'required',
    isolation,
    transform,
  };
}

function sandboxedIframeIsolation(): SandboxedIframeIsolation {
  return {
    kind: 'sandboxed_iframe',
    sandboxTokens: EMPTY_SANDBOX_TOKENS,
    allowScripts: false,
    allowForms: false,
    allowNavigation: false,
  };
}

function downloadPlan(
  mimeType: string | null,
  reason: ArtifactPreviewFallbackReason,
): ArtifactPreviewPlan {
  return {
    kind: 'download',
    mimeType: mimeType ?? '',
    reason,
  };
}

function cleanupCommands(
  active: ArtifactPreviewLifecycleActive | null,
): ArtifactPreviewCleanupCommand[] {
  if (!active) return [];
  const commands: ArtifactPreviewCleanupCommand[] = [];
  if (active.phase === 'loading') {
    commands.push({ type: 'abort_request', requestId: active.requestId });
  }
  if (active.objectUrl) {
    commands.push({ type: 'revoke_object_url', url: active.objectUrl });
  }
  return commands;
}

function normalizeMime(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.split(';', 1)[0]?.trim().toLowerCase() ?? '';
  return normalized.includes('/') ? normalized : null;
}

function identifier(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized ? normalized : null;
}

function isByteCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function isBlobObjectUrl(value: unknown): value is string {
  return typeof value === 'string' && /^blob:[^\s]+$/u.test(value);
}
