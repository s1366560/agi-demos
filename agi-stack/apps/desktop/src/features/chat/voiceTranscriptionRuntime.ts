import {
  parseVoiceTranscriptMessage,
  type VoiceTranscriptionConnection,
  type VoiceTranscriptionFailureCode,
} from './voiceTranscriptionModel';

export type VoiceTranscriptionState = 'idle' | 'connecting' | 'listening' | 'error';

type VoiceSocketMessage = { data: unknown };

export type VoiceSocket = {
  readyState: number;
  binaryType?: string;
  onopen: (() => void) | null;
  onmessage: ((message: VoiceSocketMessage) => void) | null;
  onerror: (() => void) | null;
  onclose: (() => void) | null;
  send: (data: string | ArrayBuffer) => void;
  close: () => void;
};

export type VoiceWorkletNode = {
  port: {
    onmessage: ((event: { data: unknown }) => void) | null;
    postMessage: (message: unknown) => void;
  };
  disconnect: () => void;
};

type VoiceMediaTrack = {
  stop: () => void;
};

export type VoiceMediaStream = {
  getTracks: () => VoiceMediaTrack[];
};

type VoiceMediaStreamSource = {
  connect: (target: VoiceWorkletNode) => void;
  disconnect: () => void;
};

export type VoiceAudioContext = {
  sampleRate: number;
  state: string;
  audioWorklet: {
    addModule: (url: string) => Promise<void>;
  };
  createMediaStreamSource: (stream: VoiceMediaStream) => VoiceMediaStreamSource;
  close: () => Promise<void>;
};

export type VoiceTranscriptionRuntime = {
  createSocket: (url: string, protocols: string[]) => VoiceSocket;
  createAudioContext: () => VoiceAudioContext;
  createWorkletNode: (context: VoiceAudioContext) => VoiceWorkletNode;
  getUserMedia: () => Promise<VoiceMediaStream>;
  requestMicrophoneAccess: () => Promise<boolean>;
  workletModuleUrl: string;
  socketOpenState: number;
};

export type VoiceTranscriptionCallbacks = {
  onState: (state: VoiceTranscriptionState) => void;
  onInterim: (text: string, scopeKey: string) => void;
  onFinal: (text: string, scopeKey: string) => void;
  onError: (code: VoiceTranscriptionFailureCode, scopeKey: string) => void;
};

const DEFAULT_SPEAKER = 'zh_female_tianmeixiaoyuan_moon_bigtts';

export class VoiceTranscriptionController {
  private generation = 0;
  private socket: VoiceSocket | null = null;
  private audioContext: VoiceAudioContext | null = null;
  private workletNode: VoiceWorkletNode | null = null;
  private mediaStream: VoiceMediaStream | null = null;
  private sourceNode: VoiceMediaStreamSource | null = null;
  private scopeKey: string | null = null;
  private settleSocketOpen: ((result: boolean) => void) | null = null;

  constructor(
    private readonly runtime: VoiceTranscriptionRuntime,
    private readonly callbacks: VoiceTranscriptionCallbacks,
  ) {}

  async start(
    connection: Extract<VoiceTranscriptionConnection, { availability: 'available' }>,
  ): Promise<boolean> {
    this.stop();
    const generation = ++this.generation;
    this.scopeKey = connection.scopeKey;
    this.callbacks.onState('connecting');

    let permissionGranted = false;
    try {
      permissionGranted = await this.runtime.requestMicrophoneAccess();
    } catch {
      return this.fail('permission_denied', generation, connection.scopeKey);
    }
    if (!this.isCurrent(generation, connection.scopeKey)) return false;
    if (!permissionGranted) {
      return this.fail('permission_denied', generation, connection.scopeKey);
    }

    let socket: VoiceSocket;
    try {
      socket = this.runtime.createSocket(connection.url, connection.protocols);
      socket.binaryType = 'arraybuffer';
      this.socket = socket;
    } catch {
      return this.fail('connection_failed', generation, connection.scopeKey);
    }

    const connected = await new Promise<boolean>((resolve) => {
      let settled = false;
      const settle = (result: boolean) => {
        if (settled) return;
        settled = true;
        if (this.settleSocketOpen === settle) this.settleSocketOpen = null;
        resolve(result);
      };
      this.settleSocketOpen = settle;
      socket.onopen = () => settle(this.isCurrent(generation, connection.scopeKey));
      socket.onerror = () => settle(false);
      socket.onclose = () => settle(false);
    });
    if (!connected || !this.isCurrent(generation, connection.scopeKey)) {
      if (this.isCurrent(generation, connection.scopeKey)) {
        return this.fail('connection_failed', generation, connection.scopeKey);
      }
      return false;
    }

    try {
      socket.send(
        JSON.stringify({
          type: 'voice_config',
          sample_rate: 16000,
          speaker: DEFAULT_SPEAKER,
        }),
      );
      this.installSocketHandlers(socket, generation, connection.scopeKey);
      const audioContext = this.runtime.createAudioContext();
      this.audioContext = audioContext;
      await audioContext.audioWorklet.addModule(this.runtime.workletModuleUrl);
      if (!this.isCurrent(generation, connection.scopeKey)) return false;

      const workletNode = this.runtime.createWorkletNode(audioContext);
      this.workletNode = workletNode;
      workletNode.port.postMessage({
        type: 'config',
        sampleRate: audioContext.sampleRate,
      });
      workletNode.port.onmessage = (event) => {
        if (!this.isCurrent(generation, connection.scopeKey)) return;
        const activeSocket = this.socket;
        if (
          activeSocket?.readyState === this.runtime.socketOpenState &&
          event.data instanceof Int16Array
        ) {
          const payload = new ArrayBuffer(event.data.byteLength);
          new Int16Array(payload).set(event.data);
          activeSocket.send(payload);
        }
      };

      const stream = await this.runtime.getUserMedia();
      if (!this.isCurrent(generation, connection.scopeKey)) {
        stream.getTracks().forEach((track) => track.stop());
        return false;
      }
      this.mediaStream = stream;
      const sourceNode = audioContext.createMediaStreamSource(stream);
      this.sourceNode = sourceNode;
      sourceNode.connect(workletNode);
      this.callbacks.onState('listening');
      return true;
    } catch (error) {
      const code = voiceCaptureFailureCode(error);
      return this.fail(code, generation, connection.scopeKey);
    }
  }

  stop(): void {
    this.generation += 1;
    this.releaseResources();
    this.scopeKey = null;
    this.callbacks.onState('idle');
  }

  private installSocketHandlers(socket: VoiceSocket, generation: number, scopeKey: string): void {
    socket.onmessage = (event) => {
      if (!this.isCurrent(generation, scopeKey) || typeof event.data !== 'string') return;
      const message = parseVoiceTranscriptMessage(event.data);
      if (message.kind === 'interim') this.callbacks.onInterim(message.text, scopeKey);
      if (message.kind === 'final') this.callbacks.onFinal(message.text, scopeKey);
      if (message.kind === 'error') this.fail('service_error', generation, scopeKey);
    };
    socket.onerror = () => {
      if (this.isCurrent(generation, scopeKey)) {
        this.fail('connection_failed', generation, scopeKey);
      }
    };
    socket.onclose = () => {
      if (this.isCurrent(generation, scopeKey)) {
        this.fail('connection_closed', generation, scopeKey);
      }
    };
  }

  private isCurrent(generation: number, scopeKey: string): boolean {
    return this.generation === generation && this.scopeKey === scopeKey;
  }

  private fail(code: VoiceTranscriptionFailureCode, generation: number, scopeKey: string): false {
    if (!this.isCurrent(generation, scopeKey)) return false;
    this.callbacks.onError(code, scopeKey);
    this.generation += 1;
    this.releaseResources();
    this.scopeKey = null;
    this.callbacks.onState('error');
    return false;
  }

  private releaseResources(): void {
    this.settleSocketOpen?.(false);
    this.settleSocketOpen = null;
    if (this.workletNode) {
      this.workletNode.port.onmessage = null;
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }
    if (this.audioContext) {
      if (this.audioContext.state !== 'closed') {
        void this.audioContext.close().catch(() => undefined);
      }
      this.audioContext = null;
    }
    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      socket.close();
    }
  }
}

function voiceCaptureFailureCode(error: unknown): VoiceTranscriptionFailureCode {
  if (
    error instanceof DOMException &&
    (error.name === 'NotAllowedError' || error.name === 'SecurityError')
  ) {
    return 'permission_denied';
  }
  if (error instanceof DOMException && error.name === 'NotSupportedError') {
    return 'capture_unsupported';
  }
  return 'capture_failed';
}
