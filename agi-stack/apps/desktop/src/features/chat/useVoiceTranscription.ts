import { useRef, useState } from 'react';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopVoiceSessionOperationsV2 } from '../../plugins/desktopVoiceSessionAuthorityModuleV2';
import type {
  VoiceTranscriptionConnection,
  VoiceTranscriptionFailureCode,
} from './voiceTranscriptionModel';
import {
  VoiceTranscriptionController,
  type VoiceTranscriptionState,
} from './voiceTranscriptionRuntime';
import { useVoiceSessionLeaseV2 } from './useVoiceSessionLeaseV2';

type UseVoiceTranscriptionOptions = {
  config: DesktopRuntimeConfig | null;
  operations: DesktopVoiceSessionOperationsV2;
  connection: VoiceTranscriptionConnection;
  onInterim: (text: string) => void;
  onFinal: (text: string) => void;
};

type UseVoiceTranscriptionResult = {
  state: VoiceTranscriptionState;
  errorCode: VoiceTranscriptionFailureCode | null;
  toggle: () => Promise<boolean>;
  stop: () => void;
};

export function useVoiceTranscription({
  config,
  operations,
  connection,
  onInterim,
  onFinal,
}: UseVoiceTranscriptionOptions): UseVoiceTranscriptionResult {
  const [state, setState] = useState<VoiceTranscriptionState>('idle');
  const [errorCode, setErrorCode] = useState<VoiceTranscriptionFailureCode | null>(null);
  const callbacksRef = useRef({ onInterim, onFinal });
  callbacksRef.current = { onInterim, onFinal };
  const session = useVoiceSessionLeaseV2<VoiceTranscriptionController>(
    config,
    connection,
    operations,
    () => {
      setState('idle');
      setErrorCode(null);
    },
  );
  const stop = () => {
    if (!session.isContextCurrent()) return;
    void session.stop();
    setState('idle');
    setErrorCode(null);
  };
  const toggle = async () => {
    if (!session.isContextCurrent()) return false;
    if (session.current()) {
      stop();
      return true;
    }
    if (!config || connection.availability !== 'available') return false;
    const requestConfig = Object.freeze({ ...config });
    const requestConnection = structuredClone(connection);
    setErrorCode(null);
    setState('connecting');
    try {
      return await session.start(
        (signal) =>
          operations.acquireTranscription({
            config: requestConfig,
            connection: requestConnection,
            signal,
          }),
        (runtime, guard) =>
          new VoiceTranscriptionController(runtime, {
            onState: (next) => {
              if (guard.isActive()) {
                setState(next);
                if (next === 'error') guard.finish();
              }
            },
            onInterim: (text, scopeKey) => {
              if (guard.isActive() && scopeKey === requestConnection.scopeKey)
                callbacksRef.current.onInterim(text);
            },
            onFinal: (text, scopeKey) => {
              if (guard.isActive() && scopeKey === requestConnection.scopeKey)
                callbacksRef.current.onFinal(text);
            },
            onError: (code, scopeKey) => {
              if (guard.isActive() && scopeKey === requestConnection.scopeKey) setErrorCode(code);
            },
          }),
        (controller) => controller.start(requestConnection),
      );
    } catch {
      if (session.isContextCurrent()) {
        setState('error');
        setErrorCode('connection_failed');
      }
      return false;
    }
  };
  return { state, errorCode, toggle, stop };
}
