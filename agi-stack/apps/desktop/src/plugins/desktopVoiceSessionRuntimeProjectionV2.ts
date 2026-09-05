import {
  CLOUD_SOCKET_OPEN,
  createCloudSocketBridge,
  desktopCloudSocketTransport,
  type CloudSocketBridgeTransport,
  type CloudSocketBridgeRequest,
} from '../api/cloudSocketBridge';
import type {
  VoiceTranscriptionRuntime,
  VoiceAudioContext,
  VoiceSocket,
  VoiceWorkletNode,
  VoiceMediaStream,
} from '../features/chat/voiceTranscriptionRuntime';
import type { VoiceCallRuntime, VoicePlaybackContext } from '../features/chat/voiceCallRuntime';
import {
  voiceSessionErrorV2,
  type PreparedVoiceSessionV2,
  type VoiceSessionRuntimeV2,
} from './desktopVoiceSessionContractV2';

export function createVoiceSessionRuntimeProjectionV2(
  input: PreparedVoiceSessionV2,
  kind: 'transcription' | 'call',
): VoiceSessionRuntimeV2 {
  if (input.config.mode !== 'cloud' || input.connection.availability !== 'available')
    throw voiceSessionErrorV2('unavailable');
  const connection = input.connection;
  const native = connection.transport === 'electron' ? desktopCloudSocketTransport() : null;
  if (connection.transport === 'electron' && !native)
    throw voiceSessionErrorV2('native_transport_unavailable');
  const common = {
    createSocket: (url: string, protocols: string[]): VoiceSocket =>
      native
        ? createRetainedNativeVoiceSocketV2({ kind: 'voice', url, scope: connection.scope }, native)
        : (new WebSocket(url, protocols) as unknown as VoiceSocket),
    createWorkletNode: (context: VoiceAudioContext): VoiceWorkletNode =>
      new AudioWorkletNode(
        context as unknown as BaseAudioContext,
        'audio-processor',
      ) as unknown as VoiceWorkletNode,
    getUserMedia: (): Promise<VoiceMediaStream> =>
      navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      }) as unknown as Promise<VoiceMediaStream>,
    requestMicrophoneAccess: async (): Promise<boolean> => {
      const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
      return invoke ? ((await invoke('request_microphone_access')) as unknown) === true : true;
    },
    workletModuleUrl: new URL('audio-processor.js', document.baseURI).toString(),
    socketOpenState: CLOUD_SOCKET_OPEN,
  };
  return kind === 'transcription'
    ? ({
        ...common,
        createAudioContext: () => new AudioContext() as unknown as VoiceAudioContext,
      } satisfies VoiceTranscriptionRuntime)
    : ({
        ...common,
        createCaptureContext: () => new AudioContext() as unknown as VoiceAudioContext,
        createPlaybackContext: () => new AudioContext() as unknown as VoicePlaybackContext,
      } satisfies VoiceCallRuntime);
}

function createRetainedNativeVoiceSocketV2(
  request: CloudSocketBridgeRequest,
  native: CloudSocketBridgeTransport,
): VoiceSocket {
  const pending = new Set<Promise<void>>();
  let opening: Promise<void> = Promise.resolve();
  let unsubscribe: (() => void) | undefined;
  const closeErrors: unknown[] = [];
  const track = (promise: Promise<void>): Promise<void> => {
    pending.add(promise);
    void promise.then(
      () => pending.delete(promise),
      () => pending.delete(promise),
    );
    return promise;
  };
  const transport: CloudSocketBridgeTransport = {
    subscribe(listener) {
      unsubscribe = native.subscribe(listener);
      return () => {
        unsubscribe?.();
        unsubscribe = undefined;
      };
    },
    open(input) {
      opening = track(native.open(input));
      return opening;
    },
    send(input) {
      return track(native.send(input));
    },
    close(input) {
      // A close racing native open must also close the socket created by that late open.
      return track(
        (async () => {
          await opening.catch(() => undefined);
          try {
            await native.close(input);
          } catch (error) {
            closeErrors.push(error);
            throw error;
          } finally {
            unsubscribe?.();
            unsubscribe = undefined;
          }
        })(),
      );
    },
  };
  const socket = createCloudSocketBridge(request, transport);
  let closing: Promise<void> | undefined;
  return new Proxy({} as VoiceSocket, {
    get(_target, key) {
      if (key === 'close')
        return () => {
          if (!closing) {
            socket.close();
            closing = (async () => {
              while (pending.size) await Promise.allSettled([...pending]);
              if (closeErrors.length) throw closeErrors[0];
            })();
            void closing.catch(() => undefined);
          }
          return closing;
        };
      const value: unknown = Reflect.get(socket, key, socket);
      return typeof value === 'function' ? value.bind(socket) : value;
    },
    set(_target, key, value) {
      return Reflect.set(socket, key, value, socket);
    },
  });
}
