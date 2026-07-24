import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type {
  VoiceTranscriptionConnection,
  VoiceTranscriptionFailureCode,
} from './voiceTranscriptionModel';
import {
  VoiceTranscriptionController,
  type VoiceAudioContext,
  type VoiceMediaStream,
  type VoiceSocket,
  type VoiceTranscriptionRuntime,
  type VoiceTranscriptionState,
  type VoiceWorkletNode,
} from './voiceTranscriptionRuntime';

type UseVoiceTranscriptionOptions = {
  connection: VoiceTranscriptionConnection;
  runtime?: VoiceTranscriptionRuntime;
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
  connection,
  runtime,
  onInterim,
  onFinal,
}: UseVoiceTranscriptionOptions): UseVoiceTranscriptionResult {
  const [state, setState] = useState<VoiceTranscriptionState>('idle');
  const [errorCode, setErrorCode] = useState<VoiceTranscriptionFailureCode | null>(null);
  const callbacksRef = useRef({ onInterim, onFinal });
  callbacksRef.current = { onInterim, onFinal };
  const activeScopeRef = useRef(
    connection.availability === 'available' ? connection.scopeKey : null,
  );
  activeScopeRef.current = connection.availability === 'available' ? connection.scopeKey : null;
  const resolvedRuntime = useMemo(
    () => runtime ?? createBrowserVoiceTranscriptionRuntime(),
    [runtime],
  );
  const controller = useMemo(
    () =>
      new VoiceTranscriptionController(resolvedRuntime, {
        onState: setState,
        onInterim: (text, scopeKey) => {
          if (activeScopeRef.current === scopeKey) callbacksRef.current.onInterim(text);
        },
        onFinal: (text, scopeKey) => {
          if (activeScopeRef.current === scopeKey) callbacksRef.current.onFinal(text);
        },
        onError: (code, scopeKey) => {
          if (activeScopeRef.current === scopeKey) setErrorCode(code);
        },
      }),
    [resolvedRuntime],
  );

  const scopeKey =
    connection.availability === 'available' ? connection.scopeKey : connection.availability;
  useEffect(() => {
    controller.stop();
    setErrorCode(null);
  }, [controller, scopeKey]);
  useEffect(() => () => controller.stop(), [controller]);

  const stop = useCallback(() => {
    controller.stop();
    setErrorCode(null);
  }, [controller]);
  const toggle = useCallback(async () => {
    if (state === 'connecting' || state === 'listening') {
      stop();
      return true;
    }
    if (connection.availability !== 'available') return false;
    setErrorCode(null);
    return controller.start(connection);
  }, [connection, controller, state, stop]);

  return { state, errorCode, toggle, stop };
}

function createBrowserVoiceTranscriptionRuntime(): VoiceTranscriptionRuntime {
  return {
    createSocket: (url, protocols) => new WebSocket(url, protocols) as unknown as VoiceSocket,
    createAudioContext: () => new AudioContext() as unknown as VoiceAudioContext,
    createWorkletNode: (context) =>
      new AudioWorkletNode(
        context as unknown as BaseAudioContext,
        'audio-processor',
      ) as unknown as VoiceWorkletNode,
    getUserMedia: () =>
      navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      }) as unknown as Promise<VoiceMediaStream>,
    requestMicrophoneAccess: requestNativeMicrophoneAccess,
    workletModuleUrl: new URL('audio-processor.js', document.baseURI).toString(),
    socketOpenState: WebSocket.OPEN,
  };
}

async function requestNativeMicrophoneAccess(): Promise<boolean> {
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) return true;
  const result = (await invoke('request_microphone_access')) as unknown;
  return result === true;
}
