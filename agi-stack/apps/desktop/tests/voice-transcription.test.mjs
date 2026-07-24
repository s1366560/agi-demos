import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyVoiceTranscriptMessage,
  initialVoiceTranscriptDraft,
  parseVoiceTranscriptMessage,
  resolveVoiceTranscriptionConnection,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/voiceTranscriptionModel.js');
const {
  VoiceTranscriptionController,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/voiceTranscriptionRuntime.js');

const cloudConfig = {
  apiBaseUrl: 'https://cloud.memstack.test/base',
  apiKey: 'ms_sk_test_credential',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
};

test('voice transcription connection is cloud-only, scope-bound, and keeps auth out of URLs', () => {
  const connection = resolveVoiceTranscriptionConnection(
    cloudConfig,
    'project-1',
    'conversation-1',
  );
  assert.equal(connection.availability, 'available');
  assert.equal(
    connection.url,
    'wss://cloud.memstack.test/api/v1/voice/chat?project_id=project-1&conversation_id=conversation-1',
  );
  assert.deepEqual(connection.protocols, ['memstack.auth', 'ms_sk_test_credential']);
  assert.equal(connection.scopeKey.includes('ms_sk_test_credential'), false);
  assert.equal(connection.scopeKey.includes('conversation-1'), true);

  assert.deepEqual(
    resolveVoiceTranscriptionConnection(
      { ...cloudConfig, mode: 'local' },
      'project-1',
      'conversation-1',
    ),
    { availability: 'local_runtime' },
  );
  assert.deepEqual(
    resolveVoiceTranscriptionConnection(
      { ...cloudConfig, apiKey: '' },
      'project-1',
      'conversation-1',
    ),
    { availability: 'authentication_required' },
  );
  assert.deepEqual(resolveVoiceTranscriptionConnection(cloudConfig, '', 'conversation-1'), {
    availability: 'conversation_required',
  });
});

test('voice transcript parsing and draft projection preserve the existing draft', () => {
  let draft = initialVoiceTranscriptDraft('Existing draft: ');
  draft = applyVoiceTranscriptMessage(
    draft,
    parseVoiceTranscriptMessage(JSON.stringify({ type: 'asr_interim', text: 'hello' })),
  );
  assert.deepEqual(draft, {
    prefix: 'Existing draft: ',
    committed: '',
    interim: 'hello',
  });
  draft = applyVoiceTranscriptMessage(
    draft,
    parseVoiceTranscriptMessage(JSON.stringify({ type: 'asr_final', text: 'hello world' })),
  );
  assert.deepEqual(draft, {
    prefix: 'Existing draft: ',
    committed: 'hello world',
    interim: '',
  });
  assert.deepEqual(
    parseVoiceTranscriptMessage(JSON.stringify({ type: 'error', message: 'ASR unavailable' })),
    { kind: 'error', message: 'ASR unavailable' },
  );
  assert.deepEqual(parseVoiceTranscriptMessage('not-json'), { kind: 'ignore' });
  assert.deepEqual(
    parseVoiceTranscriptMessage(JSON.stringify({ type: 'agent_token', text: 'ignore me' })),
    { kind: 'ignore' },
  );
});

class FakeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = FakeSocket.CONNECTING;
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

function controllerFixture() {
  const socket = new FakeSocket();
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
  const audioContext = {
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
  const stream = { getTracks: () => [track] };
  const states = [];
  const interim = [];
  const finals = [];
  const errors = [];
  const runtime = {
    createSocket: () => socket,
    createAudioContext: () => audioContext,
    createWorkletNode: () => worklet,
    getUserMedia: async () => stream,
    requestMicrophoneAccess: async () => true,
    workletModuleUrl: 'https://desktop.test/audio-processor.js',
    socketOpenState: FakeSocket.OPEN,
  };
  const controller = new VoiceTranscriptionController(runtime, {
    onState: (state) => states.push(state),
    onInterim: (text, scopeKey) => interim.push([text, scopeKey]),
    onFinal: (text, scopeKey) => finals.push([text, scopeKey]),
    onError: (code, scopeKey) => errors.push([code, scopeKey]),
  });
  return {
    controller,
    runtime,
    socket,
    worklet,
    track,
    source,
    audioContext,
    states,
    interim,
    finals,
    errors,
  };
}

const connection = {
  availability: 'available',
  scopeKey: 'tenant-1\u0000project-1\u0000workspace-1\u0000conversation-1',
  url: 'wss://cloud.memstack.test/api/v1/voice/chat',
  protocols: ['memstack.auth', 'ms_sk_test_credential'],
};

test('production composer exposes scoped, localized voice dictation without auto-send', () => {
  const chatSource = readFileSync(
    new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
    'utf8',
  );
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const hookSource = readFileSync(
    new URL('../src/features/chat/useVoiceTranscription.ts', import.meta.url),
    'utf8',
  );
  const styles = readFileSync(
    new URL('../src/features/chat/ChatPanel.css', import.meta.url),
    'utf8',
  );
  const i18n = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');
  assert.match(chatSource, /useVoiceTranscription/);
  assert.match(chatSource, /resolveVoiceTranscriptionConnection/);
  assert.match(chatSource, /composer\.voice\.start/);
  assert.match(chatSource, /aria-pressed=\{voiceActive\}/);
  assert.match(chatSource, /voice\.stop\(\);[\s\S]*onSend\(/);
  assert.match(appSource, /voiceTranscriptionConfig=\{config\}/);
  assert.match(hookSource, /\[controller, scopeKey\]/);
  assert.match(styles, /\.composer-voice-button\.is-listening/);
  assert.match(styles, /prefers-reduced-motion:\s*reduce/);
  assert.match(i18n, /'composer\.voice\.start': 'Voice input'/);
  assert.match(i18n, /'composer\.voice\.start': '语音输入'/);
  assert.equal(existsSync(new URL('../qa/voice-transcription.html', import.meta.url)), true);
  assert.equal(existsSync(new URL('../src/qa/VoiceTranscriptionQa.tsx', import.meta.url)), true);
});

test('voice transcription controller streams PCM, dispatches text, and releases every resource', async () => {
  const fixture = controllerFixture();
  const started = fixture.controller.start(connection);
  await Promise.resolve();
  fixture.socket.open();
  assert.equal(await started, true);
  assert.deepEqual(JSON.parse(fixture.socket.sent[0]), {
    type: 'voice_config',
    sample_rate: 16000,
    speaker: 'zh_female_tianmeixiaoyuan_moon_bigtts',
  });
  assert.deepEqual(fixture.audioContext.audioWorklet.modules, [
    'https://desktop.test/audio-processor.js',
  ]);
  assert.deepEqual(fixture.worklet.port.messages, [{ type: 'config', sampleRate: 48000 }]);
  assert.equal(fixture.source.connectTarget, fixture.worklet);

  fixture.socket.onmessage?.({
    data: JSON.stringify({ type: 'asr_interim', text: 'hello' }),
  });
  fixture.socket.onmessage?.({
    data: JSON.stringify({ type: 'asr_final', text: 'hello world' }),
  });
  fixture.worklet.port.onmessage?.({ data: new Int16Array([1, -1]) });
  assert.deepEqual(fixture.interim, [['hello', connection.scopeKey]]);
  assert.deepEqual(fixture.finals, [['hello world', connection.scopeKey]]);
  assert.equal(fixture.socket.sent[1] instanceof ArrayBuffer, true);
  assert.equal(fixture.states.at(-1), 'listening');

  fixture.controller.stop();
  assert.equal(fixture.worklet.disconnected, true);
  assert.equal(fixture.source.disconnected, true);
  assert.equal(fixture.track.stopped, true);
  assert.equal(fixture.audioContext.closeCalls, 1);
  assert.equal(fixture.socket.closeCalls, 1);
  assert.equal(fixture.states.at(-1), 'idle');
});

test('stopping while the voice socket connects settles start and closes the socket', async () => {
  const fixture = controllerFixture();
  const started = fixture.controller.start(connection);
  await Promise.resolve();
  await Promise.resolve();

  fixture.controller.stop();

  assert.equal(await started, false);
  assert.equal(fixture.socket.closeCalls, 1);
  assert.deepEqual(fixture.states, ['idle', 'connecting', 'idle']);
});

test('voice transcription controller fails closed when native microphone access is denied', async () => {
  const fixture = controllerFixture();
  fixture.runtime.requestMicrophoneAccess = async () => false;
  assert.equal(await fixture.controller.start(connection), false);
  assert.deepEqual(fixture.errors, [['permission_denied', connection.scopeKey]]);
  assert.equal(fixture.socket.sent.length, 0);
  assert.equal(fixture.states.at(-1), 'error');
});
