import type { DesktopRuntimeConfig } from '../../types';
import {
  resolveVoiceTranscriptionConnection,
  type VoiceTranscriptionConnection,
} from './voiceTranscriptionModel';

export type VoiceCallConnection = VoiceTranscriptionConnection;

export type VoiceCallStatus = 'idle' | 'connecting' | 'connected' | 'error' | 'ended';

export type VoiceCallMessage =
  | { kind: 'asr_interim'; text: string }
  | { kind: 'asr_final'; text: string }
  | { kind: 'agent_token'; content: string }
  | { kind: 'agent_complete'; content: string }
  | { kind: 'tts_start' }
  | { kind: 'tts_end' }
  | { kind: 'error'; message: string }
  | { kind: 'ignore' };

export type VoiceCallTranscript = {
  asrInterim: string;
  asrFinal: string;
  agentResponse: string;
  agentStreaming: boolean;
};

export type VoiceCallFailureCode =
  | 'permission_denied'
  | 'capture_unsupported'
  | 'connection_failed'
  | 'connection_closed'
  | 'capture_failed'
  | 'playback_failed'
  | 'service_error';

export function resolveVoiceCallConnection(
  config: Pick<
    DesktopRuntimeConfig,
    'apiBaseUrl' | 'apiKey' | 'tenantId' | 'projectId' | 'workspaceId' | 'mode'
  >,
  projectId: string,
  conversationId: string,
): VoiceCallConnection {
  return resolveVoiceTranscriptionConnection(config, projectId, conversationId);
}

export function parseVoiceCallMessage(data: string): VoiceCallMessage {
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
    return { kind: 'asr_interim', text: record.text };
  }
  if (record.type === 'asr_final' && typeof record.text === 'string') {
    return { kind: 'asr_final', text: record.text };
  }
  if (record.type === 'agent_token' && typeof record.content === 'string') {
    return { kind: 'agent_token', content: record.content };
  }
  if (record.type === 'agent_complete' && typeof record.content === 'string') {
    return { kind: 'agent_complete', content: record.content };
  }
  if (record.type === 'tts_start') return { kind: 'tts_start' };
  if (record.type === 'tts_end') return { kind: 'tts_end' };
  if (record.type === 'error' && typeof record.message === 'string') {
    return { kind: 'error', message: record.message };
  }
  return { kind: 'ignore' };
}

export function initialVoiceCallTranscript(): VoiceCallTranscript {
  return {
    asrInterim: '',
    asrFinal: '',
    agentResponse: '',
    agentStreaming: false,
  };
}

export function reduceVoiceCallTranscript(
  transcript: VoiceCallTranscript,
  message: VoiceCallMessage,
): VoiceCallTranscript {
  if (message.kind === 'asr_interim') {
    return { ...transcript, asrInterim: message.text };
  }
  if (message.kind === 'asr_final') {
    return { ...transcript, asrInterim: '', asrFinal: message.text };
  }
  if (message.kind === 'agent_token') {
    return {
      ...transcript,
      agentResponse: `${transcript.agentResponse}${message.content}`,
      agentStreaming: true,
    };
  }
  if (message.kind === 'agent_complete') {
    return {
      ...transcript,
      agentResponse: message.content,
      agentStreaming: false,
    };
  }
  return transcript;
}

export function formatVoiceCallDuration(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safeSeconds / 3_600);
  const minutes = Math.floor((safeSeconds % 3_600) / 60);
  const seconds = safeSeconds % 60;
  const minuteSecond = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  return hours > 0 ? `${hours}:${minuteSecond}` : minuteSecond;
}

export function voiceCallFailureKey(code: VoiceCallFailureCode): string {
  return `composer.voiceCall.error.${code}`;
}
