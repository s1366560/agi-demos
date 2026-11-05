import type { DesktopRuntimeConfig } from '../types';

export type AudioSession = Readonly<{
  audio_session_id: string;
  generation: number;
  state: 'starting' | 'recording' | 'paused' | 'interrupted' | 'stopped' | 'completed' | 'failed';
  source: 'microphone' | 'system' | 'mixed';
  started_at: string;
  captured_ms: number;
  max_duration_ms: number;
  provider_profile_id?: string;
  error_code?: string;
  segments: readonly { segment_id: string; source: string; start_ms: number; end_ms: number }[];
  transcript: readonly { segment_id: string; text: string; start_ms?: number; end_ms?: number; speaker_id?: string }[];
  summary?: { text: string };
}>;
export type SpeechProfile = Readonly<{ id: string; name: string; provider: string; app_id: string }>;
export type AudioSessionsSnapshot = Readonly<{
  scope: { tenant_id: string; project_id: string };
  sessions: readonly AudioSession[];
  profiles: readonly SpeechProfile[];
}>;
export type AudioSessionOperation = Readonly<{
  action: 'list' | 'start' | 'pause' | 'resume' | 'stop' | 'status' | 'configure_provider' | 'retry_transcription';
  audio_session_id?: string;
  generation?: number;
  source?: AudioSession['source'];
  max_duration_ms?: number;
  provider_profile_id?: string;
  name?: string;
  app_id?: string;
  access_token?: string;
}>;
export type AudioSessionsClient = Readonly<{
  manage(operation: AudioSessionOperation, signal?: AbortSignal): Promise<AudioSessionsSnapshot>;
}>;

export function createAudioSessionsClient(config: DesktopRuntimeConfig): AudioSessionsClient {
  const scope = Object.freeze({ mode: config.mode, tenant_id: config.tenantId, project_id: config.projectId,
    credential: config.mode === 'local' ? config.apiKey : '' });
  return Object.freeze({
    async manage(operation: AudioSessionOperation, signal?: AbortSignal) {
      signal?.throwIfAborted();
      const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
      if (!invoke) throw new Error('audio_session_native_unavailable');
      const value = await invoke('audio_sessions_manage_v2', { input: { ...scope, operation } }) as AudioSessionsSnapshot;
      signal?.throwIfAborted();
      if (!value || value.scope?.tenant_id !== scope.tenant_id || value.scope?.project_id !== scope.project_id ||
        !Array.isArray(value.sessions) || !Array.isArray(value.profiles)) throw new Error('audio_session_snapshot_invalid');
      return value;
    },
  });
}
