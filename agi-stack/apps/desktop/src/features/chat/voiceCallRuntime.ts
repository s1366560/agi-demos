import {
  parseVoiceCallMessage,
  type VoiceCallConnection,
  type VoiceCallFailureCode,
  type VoiceCallMessage,
  type VoiceCallStatus,
} from './voiceCallModel';
import type {
  VoiceAudioContext,
  VoiceMediaStream,
  VoiceSocket,
  VoiceWorkletNode,
} from './voiceTranscriptionRuntime';

type VoiceMediaStreamSource = {
  connect: (target: VoiceWorkletNode) => void;
  disconnect: () => void;
};

export type VoicePlaybackBuffer = {
  duration: number;
};

export type VoicePlaybackSource = {
  buffer: VoicePlaybackBuffer | null;
  onended: (() => void) | null;
  connect: (destination: unknown) => void;
  disconnect: () => void;
  start: (when: number) => void;
  stop: () => void;
};

export type VoicePlaybackContext = {
  state: string;
  currentTime: number;
  destination: unknown;
  resume: () => Promise<void>;
  decodeAudioData: (data: ArrayBuffer) => Promise<VoicePlaybackBuffer>;
  createBufferSource: () => VoicePlaybackSource;
  close: () => Promise<void>;
};

export type VoiceCallRuntime = {
  createSocket: (url: string, protocols: string[]) => VoiceSocket;
  createCaptureContext: () => VoiceAudioContext;
  createWorkletNode: (context: VoiceAudioContext) => VoiceWorkletNode;
  getUserMedia: () => Promise<VoiceMediaStream>;
  requestMicrophoneAccess: () => Promise<boolean>;
  createPlaybackContext: () => VoicePlaybackContext;
  workletModuleUrl: string;
  socketOpenState: number;
};

export type VoiceCallCallbacks = {
  onState: (state: VoiceCallStatus) => void;
  onMessage: (message: VoiceCallMessage, scopeKey: string) => void;
  onSpeaking: (speaking: boolean, scopeKey: string) => void;
  onError: (code: VoiceCallFailureCode, scopeKey: string) => void;
};

const DEFAULT_SPEAKER = 'zh_female_tianmeixiaoyuan_moon_bigtts';

class VoiceTtsPlaybackQueue {
  private generation = 0;
  private context: VoicePlaybackContext | null = null;
  private readonly sources = new Set<VoicePlaybackSource>();
  private nextStartTime = 0;
  private sequence = Promise.resolve();

  constructor(
    private readonly createContext: () => VoicePlaybackContext,
    private readonly onPlayingChange: (playing: boolean) => void,
    private readonly onError: () => void,
  ) {}

  enqueue(data: ArrayBuffer): void {
    const generation = this.generation;
    const payload = data.slice(0);
    this.sequence = this.sequence
      .then(() => this.schedule(payload, generation))
      .catch(() => {
        if (generation === this.generation) this.onError();
      });
  }

  stop(): void {
    this.generation += 1;
    this.sequence = Promise.resolve();
    for (const source of this.sources) {
      source.onended = null;
      try {
        source.disconnect();
        source.stop();
      } catch {
        // A source may have completed between the queue snapshot and cleanup.
      }
    }
    this.sources.clear();
    this.nextStartTime = 0;
    this.onPlayingChange(false);
    if (this.context) {
      const context = this.context;
      this.context = null;
      if (context.state !== 'closed') void context.close().catch(() => undefined);
    }
  }

  private async schedule(data: ArrayBuffer, generation: number): Promise<void> {
    if (generation !== this.generation) return;
    const context = this.context ?? this.createContext();
    this.context = context;
    if (context.state === 'suspended') await context.resume();
    const buffer = await context.decodeAudioData(data);
    if (generation !== this.generation || this.context !== context) return;

    const now = context.currentTime;
    if (this.nextStartTime < now) this.nextStartTime = now + 0.05;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.onended = () => {
      this.sources.delete(source);
      source.disconnect();
      if (this.sources.size === 0) this.onPlayingChange(false);
    };
    this.sources.add(source);
    this.onPlayingChange(true);
    source.start(this.nextStartTime);
    this.nextStartTime += buffer.duration;
  }
}

export class VoiceCallController {
  private generation = 0;
  private captureGeneration = 0;
  private socket: VoiceSocket | null = null;
  private captureContext: VoiceAudioContext | null = null;
  private workletNode: VoiceWorkletNode | null = null;
  private mediaStream: VoiceMediaStream | null = null;
  private sourceNode: VoiceMediaStreamSource | null = null;
  private scopeKey: string | null = null;
  private settleSocketOpen: ((result: boolean) => void) | null = null;
  private captureStart: Promise<boolean> | null = null;
  private muted = false;
  private serverSpeaking = false;
  private playbackSpeaking = false;
  private readonly playback: VoiceTtsPlaybackQueue;

  constructor(
    private readonly runtime: VoiceCallRuntime,
    private readonly callbacks: VoiceCallCallbacks,
  ) {
    this.playback = new VoiceTtsPlaybackQueue(
      () => runtime.createPlaybackContext(),
      (playing) => {
        this.playbackSpeaking = playing;
        this.emitSpeaking();
      },
      () => {
        const generation = this.generation;
        const scopeKey = this.scopeKey;
        if (scopeKey) this.fail('playback_failed', generation, scopeKey);
      },
    );
  }

  async start(
    connection: Extract<VoiceCallConnection, { availability: 'available' }>,
  ): Promise<boolean> {
    this.generation += 1;
    this.releaseResources();
    const generation = this.generation;
    this.scopeKey = connection.scopeKey;
    this.muted = false;
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
      if (!(await this.startCapture(generation, connection.scopeKey))) return false;
      if (!this.isCurrent(generation, connection.scopeKey)) return false;
      this.callbacks.onState('connected');
      return true;
    } catch (error) {
      return this.fail(
        voiceCallCaptureFailureCode(error),
        generation,
        connection.scopeKey,
      );
    }
  }

  async setMuted(muted: boolean): Promise<boolean> {
    const scopeKey = this.scopeKey;
    const generation = this.generation;
    if (!scopeKey || !this.isCurrent(generation, scopeKey)) return false;
    if (this.muted === muted) return true;
    this.muted = muted;
    if (muted) {
      this.releaseCapture();
      return true;
    }
    try {
      return await this.startCapture(generation, scopeKey);
    } catch (error) {
      return this.fail(voiceCallCaptureFailureCode(error), generation, scopeKey);
    }
  }

  stop(): void {
    const previousScope = this.scopeKey;
    this.generation += 1;
    this.releaseResources();
    this.scopeKey = null;
    this.muted = false;
    this.callbacks.onState(previousScope ? 'ended' : 'idle');
  }

  private async startCapture(generation: number, scopeKey: string): Promise<boolean> {
    if (this.muted) return true;
    if (this.captureContext && this.workletNode && this.mediaStream && this.sourceNode) {
      return true;
    }
    if (this.captureStart) return this.captureStart;

    const captureGeneration = ++this.captureGeneration;
    const start = this.createCapture(generation, captureGeneration, scopeKey);
    this.captureStart = start;
    try {
      return await start;
    } finally {
      if (this.captureStart === start) this.captureStart = null;
    }
  }

  private async createCapture(
    generation: number,
    captureGeneration: number,
    scopeKey: string,
  ): Promise<boolean> {
    const context = this.runtime.createCaptureContext();
    let worklet: VoiceWorkletNode | null = null;
    let stream: VoiceMediaStream | null = null;
    let source: VoiceMediaStreamSource | null = null;
    try {
      await context.audioWorklet.addModule(this.runtime.workletModuleUrl);
      if (!this.isCaptureCurrent(generation, captureGeneration, scopeKey)) {
        await releaseDetachedCapture(context, worklet, stream, source);
        return false;
      }
      worklet = this.runtime.createWorkletNode(context);
      worklet.port.postMessage({ type: 'config', sampleRate: context.sampleRate });
      stream = await this.runtime.getUserMedia();
      if (!this.isCaptureCurrent(generation, captureGeneration, scopeKey)) {
        await releaseDetachedCapture(context, worklet, stream, source);
        return false;
      }
      source = context.createMediaStreamSource(stream) as VoiceMediaStreamSource;
      source.connect(worklet);
      worklet.port.onmessage = (event) => {
        if (!this.isCaptureCurrent(generation, captureGeneration, scopeKey)) return;
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
      this.captureContext = context;
      this.workletNode = worklet;
      this.mediaStream = stream;
      this.sourceNode = source;
      return true;
    } catch (error) {
      await releaseDetachedCapture(context, worklet, stream, source);
      throw error;
    }
  }

  private installSocketHandlers(socket: VoiceSocket, generation: number, scopeKey: string): void {
    socket.onmessage = (event) => {
      if (!this.isCurrent(generation, scopeKey)) return;
      if (typeof event.data === 'string') {
        const message = parseVoiceCallMessage(event.data);
        if (message.kind === 'ignore') return;
        this.callbacks.onMessage(message, scopeKey);
        if (message.kind === 'tts_start') {
          this.serverSpeaking = true;
          this.emitSpeaking();
        } else if (message.kind === 'tts_end') {
          this.serverSpeaking = false;
          this.emitSpeaking();
        } else if (message.kind === 'error') {
          this.fail('service_error', generation, scopeKey);
        }
        return;
      }
      if (event.data instanceof ArrayBuffer) this.playback.enqueue(event.data);
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

  private isCaptureCurrent(
    generation: number,
    captureGeneration: number,
    scopeKey: string,
  ): boolean {
    return (
      this.isCurrent(generation, scopeKey) &&
      this.captureGeneration === captureGeneration &&
      !this.muted
    );
  }

  private fail(code: VoiceCallFailureCode, generation: number, scopeKey: string): false {
    if (!this.isCurrent(generation, scopeKey)) return false;
    this.callbacks.onError(code, scopeKey);
    this.generation += 1;
    this.releaseResources();
    this.scopeKey = null;
    this.callbacks.onState('error');
    return false;
  }

  private emitSpeaking(): void {
    if (this.scopeKey) {
      this.callbacks.onSpeaking(
        this.serverSpeaking || this.playbackSpeaking,
        this.scopeKey,
      );
    }
  }

  private releaseCapture(): void {
    this.captureGeneration += 1;
    this.captureStart = null;
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
    if (this.captureContext) {
      const context = this.captureContext;
      this.captureContext = null;
      if (context.state !== 'closed') void context.close().catch(() => undefined);
    }
  }

  private releaseResources(): void {
    this.settleSocketOpen?.(false);
    this.settleSocketOpen = null;
    this.releaseCapture();
    this.playback.stop();
    this.serverSpeaking = false;
    this.playbackSpeaking = false;
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

async function releaseDetachedCapture(
  context: VoiceAudioContext,
  worklet: VoiceWorkletNode | null,
  stream: VoiceMediaStream | null,
  source: VoiceMediaStreamSource | null,
): Promise<void> {
  if (worklet) {
    worklet.port.onmessage = null;
    worklet.disconnect();
  }
  source?.disconnect();
  stream?.getTracks().forEach((track) => track.stop());
  if (context.state !== 'closed') await context.close().catch(() => undefined);
}

function voiceCallCaptureFailureCode(error: unknown): VoiceCallFailureCode {
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
