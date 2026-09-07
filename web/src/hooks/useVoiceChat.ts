import {
  useState,
  useRef,
  useCallback,
  useLayoutEffect,
  useMemo,
  useSyncExternalStore,
} from 'react';

import { WebVoiceSessionV2, type WebVoiceSnapshotV2 } from '@/services/voiceRetainedSessionV2';

import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';

export interface UseVoiceChatOptions {
  projectId: string;
  conversationId: string;
  onAsrInterim?: ((text: string) => void) | undefined;
  onAsrFinal?: ((text: string) => void) | undefined;
  onAgentToken?: ((token: string) => void) | undefined;
  onAgentComplete?: ((content: string) => void) | undefined;
  onTtsStart?: (() => void) | undefined;
  onTtsEnd?: (() => void) | undefined;
  onTtsAudio?: ((data: ArrayBuffer, operation: WebOperationContextV2) => void) | undefined;
  onError?: ((error: string) => void) | undefined;
  speaker?: string | undefined;
}
export interface UseVoiceChatReturn {
  isConnected: boolean;
  isRecording: boolean;
  session: WebVoiceSessionV2 | null;
  operation: WebOperationContextV2 | null;
  stream: MediaStream | null;
  analyser: AnalyserNode | null;
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
}
const EMPTY: WebVoiceSnapshotV2 = {
  connected: false,
  recording: false,
  stream: null,
  analyser: null,
};
const retired = () => new DOMException('Voice session retired', 'AbortError');
interface Lifetime {
  identity: object;
  active: boolean;
  epoch: number;
  session: WebVoiceSessionV2 | null;
  pending?: Promise<void>;
  pendingEpoch?: number;
  draining?: WebVoiceSessionV2 | null;
}
function dispatch(
  options: UseVoiceChatOptions,
  data: string | ArrayBuffer,
  operation: WebOperationContextV2
) {
  if (data instanceof ArrayBuffer) {
    options.onTtsAudio?.(data, operation);
    return;
  }
  let message: { type?: string; text?: string; content?: string; message?: string };
  try {
    message = JSON.parse(data);
  } catch {
    return;
  }
  if (!message || typeof message !== 'object') return;
  switch (message.type) {
    case 'asr_interim':
      if (typeof message.text === 'string') options.onAsrInterim?.(message.text);
      break;
    case 'asr_final':
      if (typeof message.text === 'string') options.onAsrFinal?.(message.text);
      break;
    case 'agent_token':
      if (typeof message.content === 'string') options.onAgentToken?.(message.content);
      break;
    case 'agent_complete':
      if (typeof message.content === 'string') options.onAgentComplete?.(message.content);
      break;
    case 'tts_start':
      options.onTtsStart?.();
      break;
    case 'tts_end':
      options.onTtsEnd?.();
      break;
    case 'error':
      if (typeof message.message === 'string') options.onError?.(message.message);
      break;
  }
}
export const useVoiceChat = (options: UseVoiceChatOptions): UseVoiceChatReturn => {
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );
  const identity = useMemo(
    () => ({
      owner: availability.owner,
      projectId: options.projectId,
      conversationId: options.conversationId,
      speaker: options.speaker,
    }),
    [availability.owner, options.projectId, options.conversationId, options.speaker]
  );
  const current = useRef<Lifetime | null>(null);
  const latest = useRef(options);
  const last = useRef<WebVoiceSessionV2 | null>(null);
  const [view, setView] = useState<{
    identity: object;
    snapshot: WebVoiceSnapshotV2;
    session: WebVoiceSessionV2 | null;
  }>({ identity, snapshot: EMPTY, session: null });
  useLayoutEffect(() => {
    latest.current = options;
  });
  useLayoutEffect(() => {
    const lifetime: Lifetime = { identity, active: true, epoch: 0, session: null };
    current.current = lifetime;
    return () => {
      lifetime.active = false;
      lifetime.epoch++;
      if (lifetime.session) void lifetime.session.stop().catch(() => undefined);
    };
  }, [identity]);
  const connect = useCallback((): Promise<void> => {
    const lifetime = current.current;
    if (!lifetime || !lifetime.active || lifetime.identity !== identity)
      return Promise.reject(retired());
    if (lifetime.pending && lifetime.pendingEpoch === lifetime.epoch) return lifetime.pending;
    if (lifetime.session) {
      try {
        lifetime.session.check();
        return lifetime.session.ready.then(() => undefined);
      } catch {
        /* Drain below. */
      }
    }
    const captured = { ...latest.current };
    const epoch = lifetime.epoch;
    const valid = () => current.current === lifetime && lifetime.active && lifetime.epoch === epoch;
    lifetime.draining = last.current;
    const task = (async () => {
      if (lifetime.draining) await lifetime.draining.stop();
      if (!valid()) throw retired();
      const session = new WebVoiceSessionV2({
        projectId: captured.projectId,
        conversationId: captured.conversationId,
        speaker: captured.speaker ?? 'zh_female_tianmeixiaoyuan_moon_bigtts',
        changed: (snapshot) => {
          if (valid() && lifetime.session === session)
            setView({ identity, snapshot, session: snapshot.connected ? session : null });
        },
        message: (data, operation) => {
          if (valid() && lifetime.session === session) dispatch(captured, data, operation);
        },
        error: (error) => {
          if (valid() && lifetime.session === session)
            captured.onError?.(error instanceof Error ? error.message : 'Voice session failed');
        },
      });
      lifetime.session = session;
      last.current = session;
      await session.ready;
      if (!valid() || lifetime.session !== session) throw retired();
      session.check();
      setView({ identity, snapshot: session.getSnapshot(), session });
    })();
    lifetime.pending = task;
    lifetime.pendingEpoch = epoch;
    void task
      .finally(() => {
        if (lifetime.pending === task) delete lifetime.pending;
      })
      .catch(() => undefined);
    return task;
  }, [identity]);
  const disconnect = useCallback(async (): Promise<void> => {
    const lifetime = current.current;
    if (!lifetime || lifetime.identity !== identity) return;
    lifetime.epoch++;
    const session = lifetime.session ?? lifetime.draining;
    if (lifetime.active) setView({ identity, snapshot: EMPTY, session: null });
    const results = await Promise.allSettled([session?.stop(), lifetime.pending]);
    for (const result of results)
      if (
        result.status === 'rejected' &&
        !(result.reason instanceof DOMException && result.reason.name === 'AbortError')
      )
        throw result.reason;
  }, [identity]);
  const startRecording = useCallback(async () => {
    const lifetime = current.current;
    if (!lifetime || !lifetime.active || lifetime.identity !== identity || !lifetime.session)
      throw retired();
    const session = lifetime.session;
    try {
      await session.startRecording();
    } catch (error) {
      await session.stopRecording();
      if (
        current.current === lifetime &&
        lifetime.active &&
        lifetime.session === session &&
        !(error instanceof DOMException && error.name === 'AbortError')
      )
        session.reportRecordingError(error);
      throw error;
    }
  }, [identity]);
  const stopRecording = useCallback(() => {
    const lifetime = current.current;
    return lifetime?.identity === identity
      ? (lifetime.session?.stopRecording() ?? Promise.resolve())
      : Promise.resolve();
  }, [identity]);
  const snapshot = view.identity === identity ? view.snapshot : EMPTY;
  const session = view.identity === identity ? view.session : null;
  return {
    isConnected: snapshot.connected,
    isRecording: snapshot.recording,
    stream: snapshot.stream,
    analyser: snapshot.analyser,
    session,
    operation: session?.operation ?? null,
    connect,
    disconnect,
    startRecording,
    stopRecording,
  };
};
