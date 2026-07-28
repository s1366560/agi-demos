import type {
  ArtifactContentContractV2,
  ArtifactSaveCommandV2,
  ArtifactSaveReceipt,
} from './desktopArtifactClient';

const SHA256_CONTENT_HASH_PATTERN = /^sha256:[a-f0-9]{64}$/;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{8,128}$/;

const EDITABLE_ARTIFACT_MIME_TYPES: readonly string[] = Object.freeze([
  'application/javascript',
  'application/json',
  'application/xml',
  'application/x-yaml',
  'text/css',
  'text/csv',
  'text/html',
  'text/javascript',
  'text/markdown',
  'text/plain',
  'text/x-c',
  'text/x-c++',
  'text/x-go',
  'text/x-java',
  'text/x-php',
  'text/x-python',
  'text/x-ruby',
  'text/x-rust',
  'text/x-shellscript',
  'text/x-typescript',
  'text/xml',
  'text/yaml',
]);

export const ARTIFACT_CONFLICT_ACTIONS = Object.freeze([
  'reload_server',
  'save_copy',
  'copy_draft',
] as const);

export type ArtifactConflictAction = (typeof ARTIFACT_CONFLICT_ACTIONS)[number];

export type ArtifactContentContractReadFailure =
  | 'unsupported_contract_version'
  | 'invalid_artifact_id'
  | 'invalid_revision'
  | 'invalid_content_hash'
  | 'invalid_mime_type'
  | 'invalid_content';

export type ArtifactContentContractReadResult =
  | { ok: true; value: ArtifactContentContractV2 }
  | { ok: false; reason: ArtifactContentContractReadFailure };

export type ArtifactSaveCommandFailure =
  | 'invalid_authority'
  | 'mime_not_editable'
  | 'expected_revision_mismatch'
  | 'invalid_content'
  | 'invalid_content_hash'
  | 'invalid_idempotency_key';

export type ArtifactSaveCommandResult =
  | { ok: true; command: ArtifactSaveCommandV2 }
  | { ok: false; reason: ArtifactSaveCommandFailure };

export type ArtifactDraftConflict = {
  serverRevision: number;
  serverContentHash: string;
};

export type ArtifactDraftState = {
  phase: 'clean' | 'dirty' | 'conflict';
  authority: ArtifactContentContractV2;
  draftContent: string;
  draftContentHash: string;
  conflict: ArtifactDraftConflict | null;
};

export type ArtifactConflictResolutionPlan =
  | {
      type: 'reload_server';
      artifactId: string;
      preserveDraftUntilSuccess: true;
    }
  | {
      type: 'save_copy';
      artifactId: string;
      content: string;
      contentHash: string;
    }
  | {
      type: 'copy_draft';
      content: string;
    };

export function readArtifactContentContractV2(
  value: unknown,
): ArtifactContentContractReadResult {
  const record = recordValue(value);
  if (!record || record.contract_version !== 2) {
    return { ok: false, reason: 'unsupported_contract_version' };
  }

  const artifactId = identifier(record.artifact_id);
  if (!artifactId) return { ok: false, reason: 'invalid_artifact_id' };

  const revision = record.revision;
  if (!isRevision(revision)) return { ok: false, reason: 'invalid_revision' };

  const contentHash = record.content_hash;
  if (!isContentHash(contentHash)) {
    return { ok: false, reason: 'invalid_content_hash' };
  }

  const mimeType = normalizeArtifactMime(record.mime_type);
  if (!mimeType) return { ok: false, reason: 'invalid_mime_type' };

  if (typeof record.content !== 'string') {
    return { ok: false, reason: 'invalid_content' };
  }

  return {
    ok: true,
    value: {
      contract_version: 2,
      artifact_id: artifactId,
      revision,
      content_hash: contentHash,
      mime_type: mimeType,
      content: record.content,
    },
  };
}

export function isEditableArtifactMime(mimeType: unknown): boolean {
  const normalized = normalizeArtifactMime(mimeType);
  return normalized ? EDITABLE_ARTIFACT_MIME_TYPES.includes(normalized) : false;
}

export function createArtifactSaveCommandV2(input: {
  authority: ArtifactContentContractV2;
  draftContent: string;
  draftContentHash: string;
  expectedRevision: number;
  idempotencyKey: string;
}): ArtifactSaveCommandResult {
  const authority = readArtifactContentContractV2(input.authority);
  if (!authority.ok) return { ok: false, reason: 'invalid_authority' };
  if (!isEditableArtifactMime(authority.value.mime_type)) {
    return { ok: false, reason: 'mime_not_editable' };
  }
  if (
    !isRevision(input.expectedRevision) ||
    input.expectedRevision !== authority.value.revision
  ) {
    return { ok: false, reason: 'expected_revision_mismatch' };
  }
  if (typeof input.draftContent !== 'string') {
    return { ok: false, reason: 'invalid_content' };
  }
  if (!isContentHash(input.draftContentHash)) {
    return { ok: false, reason: 'invalid_content_hash' };
  }
  if (!isIdempotencyKey(input.idempotencyKey)) {
    return { ok: false, reason: 'invalid_idempotency_key' };
  }

  return {
    ok: true,
    command: {
      contract_version: 2,
      expected_revision: input.expectedRevision,
      content_hash: input.draftContentHash,
      idempotency_key: input.idempotencyKey,
      content: input.draftContent,
    },
  };
}

export function createArtifactDraftState(
  value: ArtifactContentContractV2,
): ArtifactDraftState | null {
  const authority = readArtifactContentContractV2(value);
  if (!authority.ok || !isEditableArtifactMime(authority.value.mime_type)) return null;
  return {
    phase: 'clean',
    authority: authority.value,
    draftContent: authority.value.content,
    draftContentHash: authority.value.content_hash,
    conflict: null,
  };
}

export function editArtifactDraft(
  state: ArtifactDraftState,
  content: string,
  contentHash: string,
): ArtifactDraftState {
  if (!isContentHash(contentHash)) return state;
  const clean =
    content === state.authority.content && contentHash === state.authority.content_hash;
  if (
    state.draftContent === content &&
    state.draftContentHash === contentHash &&
    state.phase === (clean ? 'clean' : 'dirty') &&
    state.conflict === null
  ) {
    return state;
  }
  return {
    ...state,
    phase: clean ? 'clean' : 'dirty',
    draftContent: content,
    draftContentHash: contentHash,
    conflict: null,
  };
}

export function markArtifactSaveConflict(
  state: ArtifactDraftState,
  response: {
    httpStatus: number;
    serverRevision?: number;
    serverContentHash?: string;
  },
): ArtifactDraftState | null {
  if (
    response.httpStatus !== 409 ||
    !isRevision(response.serverRevision) ||
    response.serverRevision < state.authority.revision ||
    !isContentHash(response.serverContentHash)
  ) {
    return null;
  }
  return {
    ...state,
    phase: 'conflict',
    conflict: {
      serverRevision: response.serverRevision,
      serverContentHash: response.serverContentHash,
    },
  };
}

export function planArtifactConflictResolution(
  state: ArtifactDraftState,
  action: ArtifactConflictAction,
): ArtifactConflictResolutionPlan | null {
  if (state.phase !== 'conflict' || !state.conflict) return null;
  if (action === 'reload_server') {
    return {
      type: 'reload_server',
      artifactId: state.authority.artifact_id,
      preserveDraftUntilSuccess: true,
    };
  }
  if (action === 'save_copy') {
    return {
      type: 'save_copy',
      artifactId: state.authority.artifact_id,
      content: state.draftContent,
      contentHash: state.draftContentHash,
    };
  }
  return action === 'copy_draft'
    ? {
        type: 'copy_draft',
        content: state.draftContent,
      }
    : null;
}

export function applyArtifactSaveReceipt(
  state: ArtifactDraftState,
  receipt: ArtifactSaveReceipt,
): ArtifactDraftState | null {
  if (
    identifier(receipt.artifact_id) !== state.authority.artifact_id ||
    !isRevision(receipt.revision) ||
    !isContentHash(receipt.content_hash) ||
    receipt.content_hash !== state.draftContentHash ||
    typeof receipt.duplicate !== 'boolean'
  ) {
    return null;
  }
  if (
    receipt.revision === state.authority.revision &&
    receipt.duplicate &&
    state.phase === 'clean' &&
    receipt.content_hash === state.authority.content_hash
  ) {
    return state;
  }
  if (receipt.revision <= state.authority.revision) return null;

  const authority: ArtifactContentContractV2 = {
    ...state.authority,
    revision: receipt.revision,
    content_hash: receipt.content_hash,
    content: state.draftContent,
  };
  return {
    phase: 'clean',
    authority,
    draftContent: authority.content,
    draftContentHash: authority.content_hash,
    conflict: null,
  };
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function identifier(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized ? normalized : null;
}

function normalizeArtifactMime(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.split(';', 1)[0]?.trim().toLowerCase() ?? '';
  return normalized.includes('/') ? normalized : null;
}

function isRevision(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function isContentHash(value: unknown): value is string {
  return typeof value === 'string' && SHA256_CONTENT_HASH_PATTERN.test(value);
}

function isIdempotencyKey(value: unknown): value is string {
  return typeof value === 'string' && IDEMPOTENCY_KEY_PATTERN.test(value);
}
