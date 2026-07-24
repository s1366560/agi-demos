import type { DesktopRuntimeConfig } from '../../types';

export type VoiceTranscriptionAvailability =
  | 'available'
  | 'local_runtime'
  | 'authentication_required'
  | 'conversation_required';

export type VoiceTranscriptionConnection =
  | {
      availability: 'available';
      scopeKey: string;
      url: string;
      protocols: string[];
    }
  | {
      availability: Exclude<VoiceTranscriptionAvailability, 'available'>;
    };

export type VoiceTranscriptMessage =
  | { kind: 'interim'; text: string }
  | { kind: 'final'; text: string }
  | { kind: 'error'; message: string }
  | { kind: 'ignore' };

export type VoiceTranscriptDraft = {
  prefix: string;
  committed: string;
  interim: string;
};

export type VoiceTranscriptionFailureCode =
  | 'permission_denied'
  | 'capture_unsupported'
  | 'connection_failed'
  | 'connection_closed'
  | 'capture_failed'
  | 'service_error';

export function resolveVoiceTranscriptionConnection(
  config: Pick<
    DesktopRuntimeConfig,
    'apiBaseUrl' | 'apiKey' | 'tenantId' | 'projectId' | 'workspaceId' | 'mode'
  >,
  projectId: string,
  conversationId: string,
): VoiceTranscriptionConnection {
  if (config.mode !== 'cloud') return { availability: 'local_runtime' };
  const normalizedProjectId = projectId.trim();
  const normalizedConversationId = conversationId.trim();
  if (!normalizedProjectId || !normalizedConversationId) {
    return { availability: 'conversation_required' };
  }
  const credential = config.apiKey.trim();
  if (!credential) return { availability: 'authentication_required' };

  const url = new URL('/api/v1/voice/chat', config.apiBaseUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('project_id', normalizedProjectId);
  url.searchParams.set('conversation_id', normalizedConversationId);
  return {
    availability: 'available',
    scopeKey: [
      config.apiBaseUrl.trim(),
      config.tenantId.trim(),
      normalizedProjectId,
      config.workspaceId.trim(),
      normalizedConversationId,
    ].join('\u0000'),
    url: url.toString(),
    protocols: ['memstack.auth', credential],
  };
}

export function parseVoiceTranscriptMessage(data: string): VoiceTranscriptMessage {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return { kind: 'ignore' };
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { kind: 'ignore' };
  }
  const record = value as Record<string, unknown>;
  if (record.type === 'asr_interim' && typeof record.text === 'string') {
    return { kind: 'interim', text: record.text };
  }
  if (record.type === 'asr_final' && typeof record.text === 'string') {
    return { kind: 'final', text: record.text };
  }
  if (record.type === 'error' && typeof record.message === 'string') {
    return { kind: 'error', message: record.message };
  }
  return { kind: 'ignore' };
}

export function initialVoiceTranscriptDraft(prefix: string): VoiceTranscriptDraft {
  return { prefix, committed: '', interim: '' };
}

export function applyVoiceTranscriptMessage(
  draft: VoiceTranscriptDraft,
  message: VoiceTranscriptMessage,
): VoiceTranscriptDraft {
  if (message.kind === 'interim') {
    return { ...draft, interim: message.text };
  }
  if (message.kind === 'final') {
    return {
      ...draft,
      committed: `${draft.committed}${message.text}`,
      interim: '',
    };
  }
  return draft;
}

export function voiceTranscriptDraftValue(draft: VoiceTranscriptDraft): string {
  return `${draft.prefix}${draft.committed}${draft.interim}`;
}

export function voiceTranscriptionFailureKey(code: VoiceTranscriptionFailureCode): string {
  return `composer.voice.error.${code}`;
}
