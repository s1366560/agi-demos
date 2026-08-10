import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  formatVoiceCallDuration,
  initialVoiceCallTranscript,
  parseVoiceCallMessage,
  reduceVoiceCallTranscript,
  resolveVoiceCallConnection,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/voiceCallModel.js');
const {
  VoiceCallController,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/voiceCallRuntime.js');

const cloudConfig = {
  apiBaseUrl: 'https://cloud.memstack.test/base',
  apiKey: 'ms_sk_test_credential',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
};

const connection = {
  availability: 'available',
  scopeKey: 'tenant-1\u0000project-1\u0000workspace-1\u0000conversation-1',
  url: 'wss://cloud.memstack.test/api/v1/voice/chat',
  protocols: ['memstack.auth', 'ms_sk_test_credential'],
};

test('voice call uses the scoped cloud voice endpoint without leaking credentials', () => {
  const resolved = resolveVoiceCallConnection(cloudConfig, 'project-1', 'conversation-1');
  assert.equal(resolved.availability, 'available');
  assert.equal(
    resolved.url,
    'wss://cloud.memstack.test/api/v1/voice/chat?project_id=project-1&conversation_id=conversation-1',
  );
  assert.deepEqual(resolved.protocols, ['memstack.auth', 'ms_sk_test_credential']);
  assert.equal(resolved.transport, 'web');
  assert.equal(resolved.url.includes('ms_sk_test_credential'), false);
  assert.equal(resolved.scopeKey.includes('ms_sk_test_credential'), false);
  assert.deepEqual(
    resolveVoiceCallConnection(
      { ...cloudConfig, mode: 'local' },
      'project-1',
      'conversation-1',
    ),
    { availability: 'local_runtime' },
  );
});

test('voice call parser and transcript reducer preserve structured ASR and agent events', () => {
  const messages = [
    parseVoiceCallMessage(JSON.stringify({ type: 'asr_interim', text: 'hel' })),
    parseVoiceCallMessage(JSON.stringify({ type: 'asr_final', text: 'hello' })),
    parseVoiceCallMessage(JSON.stringify({ type: 'agent_token', content: 'Hi' })),
    parseVoiceCallMessage(JSON.stringify({ type: 'agent_token', content: ' there' })),
    parseVoiceCallMessage(JSON.stringify({ type: 'agent_complete', content: 'Hi there!' })),
  ];
  assert.deepEqual(messages.map((message) => message.kind), [
    'asr_interim',
    'asr_final',
    'agent_token',
    'agent_token',
    'agent_complete',
  ]);
  const transcript = messages.reduce(reduceVoiceCallTranscript, initialVoiceCallTranscript());
  assert.deepEqual(transcript, {
    asrInterim: '',
    asrFinal: 'hello',
    agentResponse: 'Hi there!',
    agentStreaming: false,
  });
  assert.deepEqual(
    parseVoiceCallMessage(JSON.stringify({ type: 'tts_start' })),
    { kind: 'tts_start' },
  );
  assert.deepEqual(
    parseVoiceCallMessage(JSON.stringify({ type: 'error', message: 'speech unavailable' })),
    { kind: 'error', message: 'speech unavailable' },
  );
  assert.deepEqual(parseVoiceCallMessage('invalid'), { kind: 'ignore' });
  assert.equal(formatVoiceCallDuration(0), '00:00');
  assert.equal(formatVoiceCallDuration(3_661), '1:01:01');
});

class FakeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;

  readyState = FakeSocket.CONNECTING;
  binaryType = '';
  sent = [];
  closeCalls = 0;
  onopen = null;
  onmessage = null;
  onerror = null;
  onclose = null;

  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  send(value) {
    this.sent.push(value);
  }

  close() {
    this.closeCalls += 1;
    this.readyState = FakeSocket.CLOSED;
  }

  emitText(value) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }

  emitBinary(value) {
    this.onmessage?.({ data: value });
  }
}

class FakeWorkletNode {
  disconnected = false;
  port = {
    messages: [],
    onmessage: null,
    postMessage: (message) => this.port.messages.push(message),
  };

  disconnect() {
    this.disconnected = true;
  }
}

class FakePlaybackSource {
  buffer = null;
  disconnected = false;
  stopCalls = 0;
  starts = [];
  onended = null;

  connect() {}

  disconnect() {
    this.disconnected = true;
  }

  start(time) {
    this.starts.push(time);
  }

  stop() {
    this.stopCalls += 1;
  }

  end() {
    this.onended?.();
  }
}

function createCaptureFixture() {
  const worklet = new FakeWorkletNode();
  const track = {
    stopped: false,
    stop() {
      this.stopped = true;
    },
  };
  const source = {
    disconnected: false,
    connectTarget: null,
    connect(target) {
      this.connectTarget = target;
    },
    disconnect() {
      this.disconnected = true;
    },
  };
  const context = {
    sampleRate: 48_000,
    state: 'running',
    audioWorklet: {
      modules: [],
      addModule(url) {
        this.modules.push(url);
        return Promise.resolve();
      },
    },
    createMediaStreamSource() {
      return source;
    },
    closeCalls: 0,
    close() {
      this.closeCalls += 1;
      this.state = 'closed';
      return Promise.resolve();
    },
  };
  return {
    worklet,
    track,
    source,
    context,
    stream: { getTracks: () => [track] },
  };
}

function controllerFixture() {
  const socket = new FakeSocket();
  const captures = [];
  const playbackSources = [];
  const decoded = [];
  const playbackContext = {
    state: 'running',
    currentTime: 5,
    destination: {},
    closeCalls: 0,
    resumeCalls: 0,
    async resume() {
      this.resumeCalls += 1;
      this.state = 'running';
    },
    async decodeAudioData(data) {
      decoded.push(new Uint8Array(data)[0]);
      return { duration: new Uint8Array(data)[0] / 10 };
    },
    createBufferSource() {
      const source = new FakePlaybackSource();
      playbackSources.push(source);
      return source;
    },
    close() {
      this.closeCalls += 1;
      this.state = 'closed';
      return Promise.resolve();
    },
  };
  const states = [];
  const messages = [];
  const speaking = [];
  const errors = [];
  const runtime = {
    createSocket: () => socket,
    createCaptureContext: () => {
      const capture = createCaptureFixture();
      captures.push(capture);
      return capture.context;
    },
    createWorkletNode: () => captures.at(-1).worklet,
    getUserMedia: async () => captures.at(-1).stream,
    requestMicrophoneAccess: async () => true,
    playbackContext,
    createPlaybackContext() {
      assert.equal(this, runtime);
      return this.playbackContext;
    },
    workletModuleUrl: 'https://desktop.test/audio-processor.js',
    socketOpenState: FakeSocket.OPEN,
  };
  const controller = new VoiceCallController(runtime, {
    onState: (state) => states.push(state),
    onMessage: (message, scopeKey) => messages.push([message, scopeKey]),
    onSpeaking: (value, scopeKey) => speaking.push([value, scopeKey]),
    onError: (code, scopeKey) => errors.push([code, scopeKey]),
  });
  return {
    controller,
    runtime,
    socket,
    captures,
    playbackSources,
    playbackContext,
    decoded,
    states,
    messages,
    speaking,
    errors,
  };
}

async function startFixture(fixture) {
  const started = fixture.controller.start(connection);
  await Promise.resolve();
  fixture.socket.open();
  assert.equal(await started, true);
}

test('voice call controller connects, streams PCM, and projects scoped protocol events', async () => {
  const fixture = controllerFixture();
  await startFixture(fixture);
  assert.deepEqual(JSON.parse(fixture.socket.sent[0]), {
    type: 'voice_config',
    sample_rate: 16000,
    speaker: 'zh_female_tianmeixiaoyuan_moon_bigtts',
  });
  const capture = fixture.captures[0];
  capture.worklet.port.onmessage?.({ data: new Int16Array([1, -1]) });
  assert.equal(fixture.socket.sent[1] instanceof ArrayBuffer, true);
  fixture.socket.emitText({ type: 'asr_final', text: 'hello' });
  fixture.socket.emitText({ type: 'agent_token', content: 'hi' });
  fixture.socket.emitText({ type: 'tts_start' });
  assert.deepEqual(
    fixture.messages.map(([message]) => message.kind),
    ['asr_final', 'agent_token', 'tts_start'],
  );
  assert.deepEqual(fixture.speaking.at(-1), [true, connection.scopeKey]);
  assert.equal(fixture.states.at(-1), 'connected');
});

test('voice call TTS binary frames decode and schedule in FIFO order', async () => {
  const fixture = controllerFixture();
  await startFixture(fixture);
  fixture.socket.emitBinary(Uint8Array.from([2]).buffer);
  fixture.socket.emitBinary(Uint8Array.from([3]).buffer);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(fixture.decoded, [2, 3]);
  assert.deepEqual(
    fixture.playbackSources.map((source) => source.starts),
    [[5.05], [5.25]],
  );
  assert.deepEqual(fixture.speaking.at(-1), [true, connection.scopeKey]);
  fixture.socket.emitText({ type: 'tts_end' });
  fixture.playbackSources.forEach((source) => source.end());
  assert.deepEqual(fixture.speaking.at(-1), [false, connection.scopeKey]);
});

test('muting releases capture only and unmuting creates one fresh capture', async () => {
  const fixture = controllerFixture();
  await startFixture(fixture);
  const firstCapture = fixture.captures[0];
  assert.equal(await fixture.controller.setMuted(true), true);
  assert.equal(firstCapture.track.stopped, true);
  assert.equal(firstCapture.context.closeCalls, 1);
  assert.equal(fixture.socket.closeCalls, 0);
  assert.equal(await fixture.controller.setMuted(false), true);
  assert.equal(fixture.captures.length, 2);
  assert.equal(await fixture.controller.setMuted(false), true);
  assert.equal(fixture.captures.length, 2);
});

test('ending a voice call releases capture, playback, socket, and ignores stale events', async () => {
  const fixture = controllerFixture();
  await startFixture(fixture);
  fixture.socket.emitBinary(Uint8Array.from([2]).buffer);
  await Promise.resolve();
  await Promise.resolve();
  fixture.controller.stop();
  assert.equal(fixture.socket.closeCalls, 1);
  assert.equal(fixture.captures[0].track.stopped, true);
  assert.equal(fixture.captures[0].context.closeCalls, 1);
  assert.equal(fixture.playbackContext.closeCalls, 1);
  assert.equal(fixture.playbackSources[0].stopCalls, 1);
  const before = fixture.messages.length;
  fixture.socket.emitText({ type: 'agent_complete', content: 'stale' });
  assert.equal(fixture.messages.length, before);
  assert.equal(fixture.states.at(-1), 'ended');
});

test('voice call fails closed on native permission denial and connecting cancellation', async () => {
  const denied = controllerFixture();
  denied.runtime.requestMicrophoneAccess = async () => false;
  assert.equal(await denied.controller.start(connection), false);
  assert.deepEqual(denied.errors, [['permission_denied', connection.scopeKey]]);
  assert.equal(denied.socket.sent.length, 0);

  const cancelled = controllerFixture();
  const started = cancelled.controller.start(connection);
  await Promise.resolve();
  await Promise.resolve();
  cancelled.controller.stop();
  assert.equal(await started, false);
  assert.equal(cancelled.socket.closeCalls, 1);
  assert.equal(cancelled.states.at(-1), 'ended');
});

test('production composer exposes an accessible audio call without regressing dictation', () => {
  const chatSource = readFileSync(
    new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
    'utf8',
  );
  const panelSource = readFileSync(
    new URL('../src/features/chat/VoiceCallPanel.tsx', import.meta.url),
    'utf8',
  );
  const styles = readFileSync(
    new URL('../src/features/chat/ChatPanel.css', import.meta.url),
    'utf8',
  );
  const i18n = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');
  assert.match(chatSource, /useVoiceCall/);
  assert.match(chatSource, /VoiceCallPanel/);
  assert.match(chatSource, /composer\.voiceCall\.start/);
  assert.match(chatSource, /voiceCallActive/);
  assert.match(panelSource, /aria-live="polite"/);
  assert.match(panelSource, /composer\.voiceCall\.minimize/);
  assert.match(panelSource, /composer\.voiceCall\.end/);
  assert.match(styles, /\.voice-call-panel/);
  assert.match(styles, /prefers-reduced-motion:\s*reduce/);
  assert.match(i18n, /'composer\.voiceCall\.start': 'Start voice call'/);
  assert.match(i18n, /'composer\.voiceCall\.start': '开始语音通话'/);
  assert.equal(existsSync(new URL('../qa/voice-call.html', import.meta.url)), true);
  assert.equal(existsSync(new URL('../src/qa/VoiceCallQa.tsx', import.meta.url)), true);
});
