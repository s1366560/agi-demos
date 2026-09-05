import { RuntimeV2Error, type ScopeV2 } from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import { desktopCloudSocketTransport } from '../api/cloudSocketBridge';
import type { VoiceTranscriptionConnection } from '../features/chat/voiceTranscriptionModel';
import type { VoiceTranscriptionRuntime } from '../features/chat/voiceTranscriptionRuntime';
import type { VoiceCallRuntime } from '../features/chat/voiceCallRuntime';

export type VoiceSessionInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  connection: VoiceTranscriptionConnection;
  signal: AbortSignal;
}>;
export type PreparedVoiceSessionV2 = VoiceSessionInputV2 & Readonly<{ scope: ScopeV2 }>;
export type VoiceSessionRuntimeV2 = VoiceTranscriptionRuntime | VoiceCallRuntime;
export type RetainedVoiceSessionV2<T extends VoiceSessionRuntimeV2> = Readonly<{
  runtime: T;
  release(): Promise<void>;
}>;
export function voiceSessionErrorV2(reason: string): RuntimeV2Error {
  return new RuntimeV2Error('desktop_voice_session_' + reason, 'desktop_voice_session_' + reason);
}
export function prepareVoiceSessionV2(input: VoiceSessionInputV2): PreparedVoiceSessionV2 {
  if (!input || !(input.signal instanceof AbortSignal)) throw voiceSessionErrorV2('input_invalid');
  input.signal.throwIfAborted();
  const config = Object.freeze({
    mode: input.config.mode,
    apiBaseUrl: input.config.apiBaseUrl,
    apiKey: input.config.apiKey,
    localApiToken: input.config.localApiToken,
    deviceAuthorizationBaseUrl: input.config.deviceAuthorizationBaseUrl,
    tenantId: input.config.tenantId,
    projectId: input.config.projectId,
    workspaceId: input.config.workspaceId,
    workspaceRoot: input.config.workspaceRoot,
  });
  if (
    Object.values(config).some((value) => typeof value !== 'string') ||
    !['cloud', 'local'].includes(config.mode) ||
    !canonical(config.tenantId) ||
    !canonical(config.projectId)
  )
    throw voiceSessionErrorV2('scope_invalid');
  const raw = input.connection;
  if (
    !raw ||
    !['available', 'local_runtime', 'authentication_required', 'conversation_required'].includes(
      raw.availability,
    )
  )
    throw voiceSessionErrorV2('connection_invalid');
  if (raw.availability !== 'available')
    return Object.freeze({
      config,
      connection: Object.freeze({ availability: raw.availability }),
      signal: input.signal,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: config.tenantId,
        project_id: config.projectId,
      }),
    });
  if (
    !raw.scope ||
    raw.scope.tenant_id !== config.tenantId ||
    raw.scope.project_id !== config.projectId ||
    raw.scope.workspace_id !== (config.workspaceId || null) ||
    !canonical(raw.scope.conversation_id) ||
    !['web', 'electron'].includes(raw.transport) ||
    !Array.isArray(raw.protocols)
  )
    throw voiceSessionErrorV2('scope_mismatch');
  let expected: URL;
  let url: URL;
  try {
    expected = new URL('/api/v1/voice/chat', config.apiBaseUrl);
    if (!['http:', 'https:'].includes(expected.protocol) || expected.username || expected.password)
      throw new Error();
    expected.protocol = expected.protocol === 'https:' ? 'wss:' : 'ws:';
    url = new URL(raw.url);
  } catch {
    throw voiceSessionErrorV2('connection_invalid');
  }
  const query = url.searchParams;
  if (
    url.origin !== expected.origin ||
    url.pathname !== expected.pathname ||
    url.username ||
    url.password ||
    url.hash ||
    [...query.keys()].length !== 2 ||
    query.get('project_id') !== config.projectId ||
    query.get('conversation_id') !== raw.scope.conversation_id
  )
    throw voiceSessionErrorV2('connection_invalid');
  if ((desktopCloudSocketTransport() ? 'electron' : 'web') !== raw.transport)
    throw voiceSessionErrorV2('transport_mismatch');
  const protocols = raw.transport === 'electron' ? [] : ['memstack.auth', config.apiKey.trim()];
  if (
    (raw.transport === 'web' && !config.apiKey.trim()) ||
    raw.protocols.length !== protocols.length ||
    raw.protocols.some((value, index) => value !== protocols[index])
  )
    throw voiceSessionErrorV2('authentication_mismatch');
  const scopeKey = [
    config.apiBaseUrl.trim(),
    config.tenantId,
    config.projectId,
    config.workspaceId,
    raw.scope.conversation_id,
  ].join('\u0000');
  if (raw.scopeKey !== scopeKey) throw voiceSessionErrorV2('scope_mismatch');
  const connection = Object.freeze({
    ...raw,
    protocols: Object.freeze([...protocols]) as unknown as string[],
    scope: Object.freeze({ ...raw.scope }),
  });
  return Object.freeze({
    config,
    connection,
    signal: input.signal,
    scope: Object.freeze({
      kind: 'session',
      tenant_id: config.tenantId,
      project_id: config.projectId,
      session_id: raw.scope.conversation_id,
    }),
  });
}
export function requireVoiceSessionRuntimeV2(
  value: unknown,
  kind: 'transcription' | 'call',
): VoiceSessionRuntimeV2 {
  if (!value || typeof value !== 'object') throw voiceSessionErrorV2('service_invalid');
  const runtime = value as Record<string, unknown>;
  const methods = [
    'createSocket',
    'createWorkletNode',
    'getUserMedia',
    'requestMicrophoneAccess',
    ...(kind === 'call'
      ? ['createCaptureContext', 'createPlaybackContext']
      : ['createAudioContext']),
  ];
  if (
    methods.some((name) => typeof runtime[name] !== 'function') ||
    typeof runtime.workletModuleUrl !== 'string' ||
    !runtime.workletModuleUrl ||
    runtime.socketOpenState !== 1
  )
    throw voiceSessionErrorV2('service_invalid');
  return value as VoiceSessionRuntimeV2;
}
function canonical(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
