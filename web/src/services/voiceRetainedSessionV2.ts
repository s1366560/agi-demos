import {
  getWebOperationAvailabilityV2,
  runWebOperationV2,
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';
import { getAuthToken } from '@/utils/tokenResolver';

import { createWebSocketAuthProtocols, createWebSocketUrl } from './client/urlUtils';

const abortError = () => new DOMException('Voice session retired', 'AbortError');
function completion<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  void promise.catch(() => undefined);
  return { promise, resolve, reject };
}
function cancellation(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}
export interface VoiceMediaLeaseV2 {
  stream: MediaStream;
  release(): Promise<void>;
}
export interface WebVoiceSnapshotV2 {
  connected: boolean;
  recording: boolean;
  stream: MediaStream | null;
  analyser: AnalyserNode | null;
}
export interface WebVoiceSessionOptionsV2 {
  projectId: string;
  conversationId: string;
  speaker: string;
  changed(snapshot: WebVoiceSnapshotV2): void;
  message(data: string | ArrayBuffer, operation: WebOperationContextV2): void;
  error(error: unknown): void;
}
export class WebVoiceSessionV2 {
  readonly id = Object.freeze({});
  operation: WebOperationContextV2 | null = null;
  readonly ready: Promise<WebVoiceSessionV2>;
  readonly done: Promise<void>;
  private readonly controller = new AbortController();
  private readonly opened = completion<WebVoiceSessionV2>();
  private readonly closed = completion<undefined>();
  private active = true;
  private socket: WebSocket | null = null;
  private failure: { error: unknown } | undefined;
  private readonly cleanupErrors: unknown[] = [];
  private recordingEpoch = 0;
  private recordingTask: Promise<void> | undefined;
  private recordingClose: Promise<void> | undefined;
  private context: AudioContext | null = null;
  private worklet: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private media: VoiceMediaLeaseV2 | null = null;
  private snapshot: WebVoiceSnapshotV2 = {
    connected: false,
    recording: false,
    stream: null,
    analyser: null,
  };
  constructor(private readonly options: WebVoiceSessionOptionsV2) {
    const owner = getWebOperationAvailabilityV2().owner,
      token = getAuthToken();
    this.ready = this.opened.promise;
    this.done = runWebOperationV2(
      async (operation) => {
        this.operation = operation;
        operation.check();
        if (operation.owner !== owner || getWebOperationAvailabilityV2().owner !== owner)
          throw abortError();
        if (!token) throw new Error('No auth token available');
        if (!options.projectId || !options.conversationId)
          throw new Error('Missing projectId or conversationId');
        const retire = () => {
          this.retire();
        };
        operation.signal.addEventListener('abort', retire, { once: true });
        let primary: { error: unknown } | undefined;
        try {
          this.check();
          const socket = new WebSocket(
            createWebSocketUrl('/voice/chat', {
              project_id: options.projectId,
              conversation_id: options.conversationId,
            }),
            createWebSocketAuthProtocols(token)
          );
          this.socket = socket;
          socket.binaryType = 'arraybuffer';
          socket.onopen = () => {
            if (!this.live()) {
              this.closeSocket();
              return;
            }
            try {
              socket.send(
                JSON.stringify({
                  type: 'voice_config',
                  sample_rate: 16000,
                  speaker: options.speaker,
                })
              );
            } catch (error) {
              this.failure ??= { error };
              this.retire();
              return;
            }
            this.update({ connected: true });
            if (this.live()) this.opened.resolve(this);
          };
          socket.onmessage = (event) => {
            if (
              this.live() &&
              (typeof event.data === 'string' || event.data instanceof ArrayBuffer)
            )
              options.message(event.data, operation);
          };
          socket.onerror = () => {
            if (this.live()) {
              this.failure ??= { error: new Error('WebSocket connection error') };
              this.report(this.failure.error);
            }
            this.retire();
          };
          socket.onclose = () => {
            socket.onopen = null;
            socket.onmessage = null;
            socket.onerror = null;
            socket.onclose = null;
            this.socket = null;
            this.closed.resolve(undefined);
            this.retire();
          };
          await this.closed.promise;
        } catch (error) {
          primary = { error };
        }
        {
          this.retire();
          const results = await Promise.allSettled([this.closed.promise, this.stopRecording()]);
          operation.signal.removeEventListener('abort', retire);
          const errors = results
            .filter((r): r is PromiseRejectedResult => r.status === 'rejected')
            .map((r) => r.reason);
          errors.push(...this.cleanupErrors);
          if (errors.length)
            throw new WebOperationCleanupErrorV2(
              primary ? [primary.error, ...errors] : errors,
              'Voice resource cleanup failed'
            );
          if (primary) throw primary.error;
          if (this.failure) throw this.failure.error;
        }
      },
      { signal: this.controller.signal }
    ).catch((error) => {
      this.opened.reject(error);
      this.retire();
      if (!cancellation(error)) {
        this.report(error);
        throw error;
      }
    });
    void this.done.catch(() => undefined);
  }
  getSnapshot(): WebVoiceSnapshotV2 {
    return this.snapshot;
  }
  check(): void {
    if (!this.active || !this.operation) throw abortError();
    this.operation.check();
  }
  private live(): boolean {
    try {
      this.check();
      return true;
    } catch {
      return false;
    }
  }
  reportRecordingError(error: unknown): void {
    if (this.live()) this.report(error);
  }
  private report(error: unknown): void {
    try {
      this.options.error(error);
    } catch {
      /* Callback cannot block cleanup. */
    }
  }
  private update(patch: Partial<WebVoiceSnapshotV2>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    try {
      this.options.changed(this.snapshot);
    } catch {
      /* Callback cannot block cleanup. */
    }
  }
  private closeSocket(): void {
    if (!this.socket || this.socket.readyState === WebSocket.CLOSED) {
      this.closed.resolve(undefined);
      return;
    }
    try {
      this.socket.close();
    } catch (error) {
      this.cleanupErrors.push(error);
    }
  }
  private retire(): void {
    if (this.active) {
      this.active = false;
      this.recordingEpoch++;
      this.opened.reject(abortError());
      this.update({ connected: false, recording: false, stream: null, analyser: null });
      this.controller.abort();
    }
    this.closeSocket();
    // Synchronously stop existing tracks; pending capture is drained by its child operation.
    if (this.media)
      void this.media.release().catch((error) => {
        this.cleanupErrors.push(error);
      });
    if (this.worklet) this.worklet.port.onmessage = null;
  }
  stop(): Promise<void> {
    this.retire();
    return this.done;
  }
  capture(constraints: MediaStreamConstraints): Promise<VoiceMediaLeaseV2> {
    this.check();
    const operation = this.operation!;
    const ready = completion<VoiceMediaLeaseV2>(),
      released = completion<undefined>();
    let stream: MediaStream | undefined,
      stopped = false;
    const failures: unknown[] = [];
    const stopTracks = () => {
      if (stream)
        for (const track of stream.getTracks())
          try {
            track.stop();
          } catch (error) {
            failures.push(error);
          }
    };
    const stop = () => {
      if (stopped) return;
      stopped = true;
      stopTracks();
      released.resolve(undefined);
    };
    const task = operation.runChild(async (child) => {
      child.signal.addEventListener('abort', stop, { once: true });
      let primary: { error: unknown } | undefined;
      try {
        child.check();
        stream = await navigator.mediaDevices.getUserMedia(constraints);
        if (stopped) {
          stopTracks();
          throw abortError();
        }
        child.check();
        ready.resolve({
          stream,
          release: () => {
            stop();
            return task.catch((error) => {
              if (!cancellation(error)) throw error;
            });
          },
        });
        await released.promise;
      } catch (error) {
        primary = { error };
      }
      {
        child.signal.removeEventListener('abort', stop);
        stop();
        if (failures.length)
          throw new WebOperationCleanupErrorV2(
            primary ? [primary.error, ...failures] : failures,
            'Voice media cleanup failed'
          );
        if (primary) throw primary.error;
      }
    });
    void task.catch((error) => {
      ready.reject(error);
    });
    return ready.promise;
  }
  startRecording(): Promise<void> {
    if (this.snapshot.recording) return Promise.resolve();
    if (this.recordingTask) return this.recordingTask;
    const epoch = ++this.recordingEpoch;
    const check = () => {
      this.check();
      if (epoch !== this.recordingEpoch) throw abortError();
    };
    const task = (async () => {
      if (this.recordingClose) await this.recordingClose;
      check();
      if (this.socket?.readyState !== WebSocket.OPEN) throw new Error('WebSocket is not connected');
      const context = new AudioContext();
      this.context = context;
      await context.audioWorklet.addModule('/audio-processor.js');
      check();
      const worklet = new AudioWorkletNode(context, 'audio-processor');
      this.worklet = worklet;
      worklet.port.postMessage({ type: 'config', sampleRate: context.sampleRate });
      const media = await this.capture({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      this.media = media;
      check();
      const source = context.createMediaStreamSource(media.stream);
      this.source = source;
      const analyser = context.createAnalyser();
      source.connect(analyser);
      source.connect(worklet);
      worklet.port.onmessage = (event) => {
        if (
          this.live() &&
          epoch === this.recordingEpoch &&
          event.data instanceof Int16Array &&
          this.socket?.readyState === WebSocket.OPEN
        )
          this.socket.send(event.data.buffer);
      };
      this.update({ recording: true, stream: media.stream, analyser });
    })();
    this.recordingTask = task;
    void task
      .finally(() => {
        if (this.recordingTask === task) this.recordingTask = undefined;
      })
      .catch(() => undefined);
    return task;
  }
  stopRecording(): Promise<void> {
    ++this.recordingEpoch;
    this.update({ recording: false, stream: null, analyser: null });
    if (this.worklet) this.worklet.port.onmessage = null;
    if (this.recordingClose) return this.recordingClose;
    const pending = this.recordingTask;
    const cleanup = (async () => {
      if (pending) await Promise.allSettled([pending]);
      const failures: unknown[] = [];
      for (const node of [this.worklet, this.source])
        try {
          node?.disconnect();
        } catch (error) {
          failures.push(error);
        }
      this.worklet = null;
      this.source = null;
      if (this.media) {
        const media = this.media;
        this.media = null;
        try {
          await media.release();
        } catch (error) {
          failures.push(error);
        }
      }
      if (this.context) {
        const context = this.context;
        this.context = null;
        try {
          if (context.state !== 'closed') await context.close();
        } catch (error) {
          failures.push(error);
        }
      }
      this.cleanupErrors.push(...failures);
      if (this.cleanupErrors.length)
        throw new WebOperationCleanupErrorV2([...this.cleanupErrors], 'Voice audio cleanup failed');
    })();
    this.recordingClose = cleanup;
    void cleanup
      .finally(() => {
        if (this.recordingClose === cleanup) this.recordingClose = undefined;
      })
      .catch(() => undefined);
    return cleanup;
  }
}
