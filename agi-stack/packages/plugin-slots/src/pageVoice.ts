/** The socket and all media resources stay in the trusted renderer. */
export type VoiceMode = 'dictation' | 'voice';
export interface VoiceSocket {
  binaryType: string;
  readyState: number;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  send(data: string | ArrayBuffer): void;
  close(): void;
}
export type OpenVoiceSocket = (
  scope: {
    tenantId: string;
    projectId: string;
    conversationId: string;
    principalId: string;
  },
  signal: AbortSignal
) => Promise<VoiceSocket>;
export interface VoiceInput {
  socket: VoiceSocket;
  ticket: string;
  mode: VoiceMode;
  workletUrl: string;
  signal: AbortSignal;
  event(value: Record<string, unknown>): void;
  bindMute(mute: (muted: boolean) => void): void;
}

export async function runPageVoice(input: VoiceInput): Promise<void> {
  const { socket, signal, event, mode } = input;
  let stream: MediaStream | undefined;
  let context: AudioContext | undefined;
  let source: MediaStreamAudioSourceNode | undefined;
  let node: AudioWorkletNode | undefined;
  let closed = false;
  let muted = false;
  let nextPlay = 0;
  let playback = Promise.resolve();
  let complete!: () => void;
  let fail!: (error: Error) => void;
  const finished = new Promise<void>((yes, no) => {
    complete = yes;
    fail = no;
  });
  function stop() {
    complete();
  }
  const live = () => !closed && !signal.aborted;
  const check = () => {
    if (!live()) throw new DOMException('Aborted', 'AbortError');
  };
  async function capture() {
    check();
    socket.send(JSON.stringify({ type: 'voice_config', mode, sample_rate: 16000, package_ticket:input.ticket }));
    const media = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    if (!live()) {
      media.getTracks().forEach((track) => track.stop());
      return;
    }
    stream = media;
    for (const track of media.getAudioTracks()) {
      track.enabled = !muted;
      track.addEventListener('ended', stop, { once: true });
    }
    context = new AudioContext();
    await context.audioWorklet.addModule(input.workletUrl);
    check();
    if (context.state === 'suspended') await context.resume();
    check();
    source = context.createMediaStreamSource(media);
    node = new AudioWorkletNode(context, 'audio-processor');
    node.port.postMessage({ type: 'config', sampleRate: context.sampleRate });
    node.port.onmessage = ({ data }) => {
      if (!live() || muted || socket.readyState !== 1 || !(data instanceof Int16Array)) return;
      socket.send(data.slice().buffer);
      let peak = 0;
      for (const sample of data) peak = Math.max(peak, Math.abs(sample));
      event({ type: 'level', level: peak / 32768 });
    };
    source.connect(node);
    event({ type: 'connected' });
  }
  async function play(data: ArrayBuffer) {
    if (!live() || !context) return;
    const audio = await context.decodeAudioData(data);
    if (!live()) return;
    const player = context.createBufferSource();
    player.buffer = audio;
    player.connect(context.destination);
    player.onended = () => player.disconnect();
    nextPlay = Math.max(context.currentTime, nextPlay);
    player.start(nextPlay);
    nextPlay += audio.duration;
  }
  try {
    check();
    input.bindMute((value) => {
      muted = value;
      stream?.getAudioTracks().forEach((track) => {
        track.enabled = !value;
      });
    });
    signal.addEventListener('abort', stop, { once: true });
    socket.binaryType = 'arraybuffer';
    socket.onopen = () => void capture().catch(fail);
    socket.onclose = () => fail(new Error('voice_connection_closed'));
    socket.onerror = () => fail(new Error('voice_connection_failed'));
    socket.onmessage = ({ data }) => {
      if (!live()) return;
      if (data instanceof ArrayBuffer && mode === 'voice') {
        playback = playback.then(() => play(data)).catch(fail);
      } else if (typeof data === 'string') {
        let value;
        try {
          value = JSON.parse(data);
        } catch {
          return;
        }
        if (value?.type === 'error') {
          fail(new Error('voice_service_error'));
          return;
        }
        if (['asr_interim', 'asr_final'].includes(value?.type) && typeof value.text === 'string')
          event({ type: value.type, text: value.text });
        else if (
          ['agent_token', 'agent_complete'].includes(value?.type) &&
          typeof value.content === 'string'
        )
          event({ type: value.type, content: value.content });
        else if (value?.type === 'tts_start' || value?.type === 'tts_end')
          event({ type: value.type });
      }
    };
    if (socket.readyState === 1) socket.onopen();
    await finished;
  } finally {
    closed = true;
    signal.removeEventListener('abort', stop);
    socket.onopen = socket.onclose = socket.onerror = socket.onmessage = null;
    socket.close();
    if (node) {
      node.port.onmessage = null;
      node.port.close();
      node.disconnect();
    }
    source?.disconnect();
    stream?.getTracks().forEach((track) => track.stop());
    if (context && context.state !== 'closed') await context.close();
  }
}
