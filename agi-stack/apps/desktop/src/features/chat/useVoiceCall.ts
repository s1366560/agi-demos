import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  CLOUD_SOCKET_OPEN,
  createCloudSocketBridge,
  desktopCloudSocketTransport,
} from '../../api/cloudSocketBridge';

import {
  initialVoiceCallTranscript,
  reduceVoiceCallTranscript,
  type VoiceCallConnection,
  type VoiceCallFailureCode,
  type VoiceCallStatus,
  type VoiceCallTranscript,
} from './voiceCallModel';
import {
  VoiceCallController,
  type VoiceCallRuntime,
  type VoicePlaybackContext,
} from './voiceCallRuntime';
import type {
  VoiceAudioContext,
  VoiceMediaStream,
  VoiceSocket,
  VoiceWorkletNode,
} from './voiceTranscriptionRuntime';

type UseVoiceCallOptions = {
  connection: VoiceCallConnection;
  runtime?: VoiceCallRuntime;
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
  connection,
  runtime,
}: UseVoiceCallOptions): UseVoiceCallResult {
  const [status, setStatus] = useState<VoiceCallStatus>('idle');
  const [transcript, setTranscript] = useState<VoiceCallTranscript>(
    initialVoiceCallTranscript,
  );
  const [errorCode, setErrorCode] = useState<VoiceCallFailureCode | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const activeScopeRef = useRef(
    connection.availability === 'available' ? connection.scopeKey : null,
  );
  activeScopeRef.current =
    connection.availability === 'available' ? connection.scopeKey : null;

  const resolvedRuntime = useMemo(
    () => runtime ?? createVoiceCallRuntime(connection),
    [connection, runtime],
  );
  const controller = useMemo(
    () =>
      new VoiceCallController(resolvedRuntime, {
        onState: (nextStatus) => {
          setStatus(nextStatus);
          if (nextStatus === 'connected') setStartedAt(Date.now());
        },
        onMessage: (message, scopeKey) => {
          if (activeScopeRef.current === scopeKey) {
            setTranscript((current) => reduceVoiceCallTranscript(current, message));
          }
        },
        onSpeaking: (speaking, scopeKey) => {
          if (activeScopeRef.current === scopeKey) setIsSpeaking(speaking);
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
    setStatus('idle');
    setTranscript(initialVoiceCallTranscript());
    setErrorCode(null);
    setIsMuted(false);
    setIsSpeaking(false);
    setStartedAt(null);
  }, [controller, scopeKey]);
  useEffect(() => () => controller.stop(), [controller]);

  const start = useCallback(async () => {
    if (connection.availability !== 'available') return false;
    setTranscript(initialVoiceCallTranscript());
    setErrorCode(null);
    setIsMuted(false);
    setIsSpeaking(false);
    setStartedAt(null);
    return controller.start(connection);
  }, [connection, controller]);

  const end = useCallback(() => {
    controller.stop();
    setIsMuted(false);
    setIsSpeaking(false);
    setStartedAt(null);
  }, [controller]);

  const toggleMute = useCallback(async () => {
    const nextMuted = !isMuted;
    const applied = await controller.setMuted(nextMuted);
    if (applied) setIsMuted(nextMuted);
    return applied;
  }, [controller, isMuted]);

  return {
    status,
    transcript,
    errorCode,
    isMuted,
    isSpeaking,
    startedAt,
    start,
    end,
    toggleMute,
  };
}

function createVoiceCallRuntime(connection: VoiceCallConnection): VoiceCallRuntime {
  const nativeTransport =
    connection.availability === 'available' && connection.transport === 'electron'
      ? desktopCloudSocketTransport()
      : null;
  return {
    createSocket: (url, protocols) =>
      nativeTransport && connection.availability === 'available'
        ? (createCloudSocketBridge(
            {
              kind: 'voice',
              url,
              scope: connection.scope,
            },
            nativeTransport,
          ) as unknown as VoiceSocket)
        : (new WebSocket(url, protocols) as unknown as VoiceSocket),
    createCaptureContext: () => new AudioContext() as unknown as VoiceAudioContext,
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
    createPlaybackContext: () =>
      new AudioContext() as unknown as VoicePlaybackContext,
    workletModuleUrl: new URL('audio-processor.js', document.baseURI).toString(),
    socketOpenState: CLOUD_SOCKET_OPEN,
  };
}

async function requestNativeMicrophoneAccess(): Promise<boolean> {
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) return true;
  const result = (await invoke('request_microphone_access')) as unknown;
  return result === true;
}
