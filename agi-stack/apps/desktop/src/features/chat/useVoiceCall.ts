import { useState } from 'react';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopVoiceSessionOperationsV2 } from '../../plugins/desktopVoiceSessionAuthorityModuleV2';
import {
  initialVoiceCallTranscript,
  reduceVoiceCallTranscript,
  type VoiceCallConnection,
  type VoiceCallFailureCode,
  type VoiceCallStatus,
  type VoiceCallTranscript,
} from './voiceCallModel';
import { VoiceCallController } from './voiceCallRuntime';
import { useVoiceSessionLeaseV2 } from './useVoiceSessionLeaseV2';

type UseVoiceCallOptions = {
  config: DesktopRuntimeConfig | null;
  operations: DesktopVoiceSessionOperationsV2;
  connection: VoiceCallConnection;
};
export type UseVoiceCallResult = {
  status: VoiceCallStatus;
  transcript: VoiceCallTranscript;
  errorCode: VoiceCallFailureCode | null;
  isMuted: boolean;
  isSpeaking: boolean;
  startedAt: number | null;
  start: () => Promise<boolean>;
  end: () => void;
  toggleMute: () => Promise<boolean>;
};
export function useVoiceCall({
  config,
  operations,
  connection,
}: UseVoiceCallOptions): UseVoiceCallResult {
  const [status, setStatus] = useState<VoiceCallStatus>('idle');
  const [transcript, setTranscript] = useState<VoiceCallTranscript>(initialVoiceCallTranscript);
  const [errorCode, setErrorCode] = useState<VoiceCallFailureCode | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const reset = () => {
    setTranscript(initialVoiceCallTranscript());
    setErrorCode(null);
    setIsMuted(false);
    setIsSpeaking(false);
    setStartedAt(null);
  };
  const session = useVoiceSessionLeaseV2<VoiceCallController>(
    config,
    connection,
    operations,
    () => {
      setStatus('idle');
      reset();
    },
  );
  const start = async () => {
    if (!session.isContextCurrent() || !config || connection.availability !== 'available')
      return false;
    const requestConfig = Object.freeze({ ...config });
    const requestConnection = structuredClone(connection);
    reset();
    setStatus('connecting');
    try {
      return await session.start(
        (signal) =>
          operations.acquireCall({ config: requestConfig, connection: requestConnection, signal }),
        (runtime, guard) =>
          new VoiceCallController(runtime, {
            onState: (next) => {
              if (guard.isActive()) {
                setStatus(next);
                if (next === 'connected') setStartedAt(Date.now());
                if (next === 'error' || next === 'ended') guard.finish();
              }
            },
            onMessage: (message, scopeKey) => {
              if (guard.isActive() && scopeKey === requestConnection.scopeKey)
                setTranscript((current) =>
                  guard.isActive() ? reduceVoiceCallTranscript(current, message) : current,
                );
            },
            onSpeaking: (speaking, scopeKey) => {
              if (guard.isActive() && scopeKey === requestConnection.scopeKey)
                setIsSpeaking(speaking);
            },
            onError: (code, scopeKey) => {
              if (guard.isActive() && scopeKey === requestConnection.scopeKey) setErrorCode(code);
            },
          }),
        (controller) => controller.start(requestConnection),
      );
    } catch {
      if (session.isContextCurrent()) {
        setStatus('error');
        setErrorCode('connection_failed');
      }
      return false;
    }
  };
  const end = () => {
    if (!session.isContextCurrent()) return;
    void session.stop();
    setStatus('ended');
    setIsMuted(false);
    setIsSpeaking(false);
    setStartedAt(null);
  };
  const toggleMute = async () => {
    const active = session.current();
    if (!active?.controller) return false;
    const next = !isMuted;
    const applied = await active.controller.setMuted(next);
    if (!active.isActive()) return false;
    if (applied) setIsMuted(next);
    return applied;
  };
  return { status, transcript, errorCode, isMuted, isSpeaking, startedAt, start, end, toggleMute };
}
