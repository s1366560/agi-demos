import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
function harness() {
  let cursor = 0;
  const slots = [];
  let effects = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useRef(v) {
      return (slots[cursor++] ??= { current: v });
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useLayoutEffect(effect, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps))
        effects.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, effect, cleanup: effect() };
        });
    },
  };
  const cache = new Map();
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const module = { exports: {} };
    cache.set(url.href, module.exports);
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      fileName: url.pathname,
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    }).outputText;
    new Function('require', 'module', 'exports', code)(
      (name) => {
        if (name === 'react') return react;
        if (name === '../i18n') return { useI18n: () => ({ t: (key) => key }) };
        if (name.startsWith('./useConversationMessaging')) return load(new URL(name + '.ts', url));
        if (!name.startsWith('.')) return require(name);
        const compiled =
          '/tmp/agistack-desktop-test-dist/src/' +
          new URL(name + '.js', url).pathname.split('/src/')[1];
        if (name.includes('desktopConversationMessagingAuthorityModuleV2') || !existsSync(compiled))
          return load(new URL(name + '.ts', url));
        return require(compiled);
      },
      module,
      module.exports,
    );
    return module.exports;
  }
  const { useConversationMessaging } = load(
    new URL('../src/hooks/useConversationMessaging.ts', import.meta.url),
  );
  const events = [];
  const state = {
    sending: false,
    error: null,
    dataset: { messages: [], conversationsByWorkspace: {} },
    timeline: { conversationId: 'c', items: [] },
    inputs: [],
  };
  const setter = (key) => (value) => {
    events.push(key);
    state[key] = typeof value === 'function' ? value(state[key]) : value;
  };
  const created = { id: 'created', project_id: 'p' };
  const client = {
    assertActive() {},
    async createAgentConversation() {
      events.push('create');
      return created;
    },
    async bindConversationWorkspace(c) {
      events.push('bind');
      return c;
    },
    async sendMessage() {
      events.push('save');
      return { id: 'm', mentions: [] };
    },
    async runAgentMessage() {
      events.push('run');
    },
  };
  const calls = [];
  const params = {
    config: {
      mode: 'local',
      apiBaseUrl: 'http://localhost',
      apiKey: '',
      localApiToken: '',
      tenantId: 't',
      projectId: 'p',
      workspaceId: 'w',
    },
    auth: { user: { user_id: 'u' } },
    dataset: { workspaces: [] },
    agentConversationSession: null,
    selectedConversation: null,
    currentArtifactRun: null,
    sessionProjection: { capabilities: { canSendMessage: true, allowedActions: ['send_message'] } },
    permissionPreset: 'default',
    runInputReferences: [],
    runInputDelivery: null,
    runInputDeliveryOptions: [],
    sessionChatDisabledReason: null,
    localRuntimeMode: true,
    messagingOperationsV2: {
      async withOperation(input, cb) {
        calls.push(input);
        return cb(client);
      },
    },
    sessionRunInputOperationsV2: {
      async createRunInput() {
        throw Error('unexpected');
      },
    },
    socket: {
      sendAgentMessage() {
        events.push('socket');
        return false;
      },
    },
    configScopeEpochRef: { current: 0 },
    contextRevisionRef: { current: 0 },
    runInputRequestRef: { current: null },
    setDataset: setter('dataset'),
    setError: setter('error'),
    setSending: setter('sending'),
    setRunInputReferences: setter('references'),
    setRunInputs: setter('inputs'),
    setAgentConversationSession: setter('session'),
    setConversationTimeline: setter('timeline'),
    invalidateSessionAuthority() {
      events.push('invalidate');
    },
    upsertAgentTaskSignal() {
      events.push('task');
    },
    async loadConversationTimeline() {
      events.push('timeline-load');
    },
  };
  let hook;
  function render(patch = {}) {
    Object.assign(params, patch);
    cursor = 0;
    hook = useConversationMessaging({ ...params });
    for (const effect of effects.splice(0)) effect();
    return hook;
  }
  function unmount() {
    for (const slot of slots) slot?.cleanup?.();
  }
  function strict() {
    unmount();
    for (const slot of slots) if (slot?.effect) slot.cleanup = slot.effect();
  }
  render();
  return {
    params,
    client,
    state,
    events,
    calls,
    render,
    unmount,
    strict,
    get hook() {
      return hook;
    },
  };
}
for (const transition of ['project', 'conversation', 'generation', 'unmount', 'strict'])
  test(`pending creation stops after ${transition}`, async () => {
    const h = harness();
    const pending = deferred();
    h.client.createAgentConversation = () => {
      h.events.push('create');
      return pending.promise;
    };
    const send = h.hook.sendMessageContent('hello', [], () => h.events.push('saved-callback'));
    await new Promise(setImmediate);
    if (transition === 'project') h.render({ config: { ...h.params.config, projectId: 'other' } });
    if (transition === 'conversation')
      h.render({ selectedConversation: { id: 'other', project_id: 'p' } });
    if (transition === 'generation')
      h.render({ messagingOperationsV2: { ...h.params.messagingOperationsV2 } });
    if (transition === 'unmount') h.unmount();
    if (transition === 'strict') h.strict();
    const before = [...h.events];
    pending.resolve({ id: 'created', project_id: 'p' });
    await send;
    assert.deepEqual(h.events, before);
    assert.equal(h.calls[0].signal.aborted, true);
    assert.ok(!h.events.includes('bind'));
    assert.ok(!h.events.includes('socket'));
  });
test('intentional new conversation adoption continues through socket and local HTTP', async () => {
  const h = harness();
  h.params.setAgentConversationSession = (value) => {
    h.state.session = value;
    h.render({ selectedConversation: value.conversation, agentConversationSession: value });
  };
  h.render();
  await h.hook.sendMessageContent('hello', []);
  assert.ok(h.events.includes('bind'));
  assert.ok(h.events.includes('socket'));
  assert.ok(h.events.includes('run'));
  assert.equal(h.state.sending, false);
});

for (const connected of [true, false])
  test(`local selected skill reaches the Agent over ${connected ? 'WebSocket' : 'HTTP'}`, async () => {
    const h = harness();
    let sent;
    h.params.socket.sendAgentMessage = (input) => {
      sent = input;
      h.events.push('socket');
      return connected;
    };
    h.client.runAgentMessage = async (_conversation, _message, _id, execution) => {
      assert.equal(execution.forcedSkillName, 'native-audit-skill');
      assert.equal(execution.appModelContext, undefined);
      h.events.push('run');
    };
    h.render();
    await h.hook.sendMessageContent('Run the selected skill', [{
      kind: 'skill', resource_id: 'skill-uuid', label: 'Native audit',
      metadata: { execution_slot: 'skill', execution_skill_name: 'native-audit-skill' },
    }]);
    assert.equal(h.state.error, null);
    assert.equal(sent?.forcedSkillName, 'native-audit-skill');
    assert.equal(sent?.appModelContext, undefined);
    assert.equal(h.events.includes('run'), !connected);
  });
test('late workspace save cannot clear composer or start a conversation', async () => {
  const h = harness();
  const pending = deferred();
  h.client.sendMessage = () => pending.promise;
  const send = h.hook.sendMessageContent('hello', [], () => h.events.push('clear'));
  h.unmount();
  const before = [...h.events];
  pending.resolve({ id: 'm', mentions: [] });
  await send;
  assert.deepEqual(h.events, before);
});
test('same context concurrent sends keep loading until all requests settle', async () => {
  const h = harness();
  const a = deferred(),
    b = deferred();
  let count = 0;
  h.client.sendMessage = () => (count++ === 0 ? a.promise : b.promise);
  const one = h.hook.sendMessageContent('one', []),
    two = h.hook.sendMessageContent('two', []);
  a.resolve({ id: 'a', mentions: ['agent'] });
  await one;
  assert.equal(h.state.sending, true);
  b.resolve({ id: 'b', mentions: ['agent'] });
  await two;
  assert.equal(h.state.sending, false);
});
test('old callback cannot begin after selection changed', async () => {
  const h = harness();
  const old = h.hook.sendMessageContent;
  h.render({ selectedConversation: { id: 'other', project_id: 'p' } });
  await old('hello', []);
  assert.equal(h.calls.length, 0);
});
test('RunInput cancellation preserves retry key and ignores late acknowledgement', async () => {
  const h = harness();
  const pending = deferred();
  let input;
  h.render({
    selectedConversation: { id: 'c', project_id: 'p' },
    currentArtifactRun: { id: 'r', conversation_id: 'c', revision: 2, status: 'running' },
    runInputDelivery: 'queue_next',
    runInputDeliveryOptions: ['queue_next'],
    sessionRunInputOperationsV2: {
      createRunInput(value) {
        input = value;
        return pending.promise;
      },
    },
  });
  const send = h.hook.sendMessageContent('hello', [], () => h.events.push('clear'));
  const retry = h.params.runInputRequestRef.current;
  h.unmount();
  const before = [...h.events];
  pending.resolve({
    input: { id: 'i', sequence: 1 },
    conversation_id: 'c',
    message_id: 'm',
    delivery_mode: 'queue_next',
  });
  await send;
  assert.equal(input.signal.aborted, true);
  assert.deepEqual(h.events, before);
  assert.equal(h.params.runInputRequestRef.current, retry);
  assert.equal(h.calls.length, 0);
});

test('App binds the current generation coordinator and injects the required messaging operations', () => {
  const source = (file) => readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8');
  const app = source('App.tsx');
  const hook = source('hooks/useConversationMessaging.ts');
  const params = source('hooks/useAgentConversation.ts');
  assert.match(
    app,
    /const desktopConversationMessagingOperationsV2 = useMemo\(\(\) => \{\s*const actions = desktopRendererGenerationV2\.actions;\s*return createDesktopConversationMessagingOperationsV2\(\(\) => actions\);\s*\}, \[desktopRendererGenerationV2\.actions\]\)/u,
  );
  assert.match(app, /messagingOperationsV2: desktopConversationMessagingOperationsV2/u);
  assert.match(params, /messagingOperationsV2: DesktopConversationMessagingOperationsV2/u);
  assert.doesNotMatch(params, /api: DesktopApiClient/u);
  assert.match(hook, /messagingOperationsV2\.withOperation\(\{ config, signal \}/u);
  assert.doesNotMatch(
    hook,
    /\bapi\.(?:sendMessage|createAgentConversation|updateAgentConversationMode|runAgentMessage)\(/u,
  );
});

test('Local unsupported permission is rejected before socket dispatch, but routed mentions can save', async () => {
  const h = harness();
  h.render({ permissionPreset: 'full' });
  await h.hook.sendMessageContent('hello', []);
  assert.ok(!h.events.includes('socket'));
  assert.ok(!h.events.includes('run'));
  assert.ok(h.state.error);
  h.events.length = 0;
  h.client.sendMessage = async () => ({ id: 'routed', mentions: ['agent'] });
  await h.hook.sendMessageContent('hello', []);
  assert.ok(!h.events.includes('create'));
  assert.ok(!h.events.includes('socket'));
  assert.equal(h.state.error, null);
});

test('an earlier failure cannot overwrite the latest same-context send error', async () => {
  const h = harness();
  const a = deferred(),
    b = deferred();
  let calls = 0;
  h.client.sendMessage = () => (calls++ === 0 ? a.promise : b.promise);
  const one = h.hook.sendMessageContent('one', []),
    two = h.hook.sendMessageContent('two', []);
  b.reject(new Error('newest-error'));
  await two;
  const expected = h.state.error;
  a.reject(new Error('older-error'));
  await one;
  assert.equal(h.state.error, expected);
  assert.equal(h.state.sending, false);
});

test('scope change during workspace binding prevents timeline and socket next steps', async () => {
  const h = harness();
  const pending = deferred();
  h.client.bindConversationWorkspace = () => pending.promise;
  const send = h.hook.sendMessageContent('hello', []);
  await new Promise(setImmediate);
  h.render({ config: { ...h.params.config, workspaceId: 'other' } });
  const before = [...h.events];
  pending.resolve({ id: 'created', project_id: 'p' });
  await send;
  assert.deepEqual(h.events, before);
  assert.ok(!h.events.includes('socket'));
});

test('late Local HTTP completion cannot invalidate or mutate the new context', async () => {
  const h = harness();
  const pending = deferred();
  h.client.runAgentMessage = () => pending.promise;
  const send = h.hook.sendMessageContent('hello', []);
  await new Promise(setImmediate);
  assert.ok(h.events.includes('socket'));
  h.render({ config: { ...h.params.config, projectId: 'other' } });
  const before = [...h.events];
  pending.resolve({ queued: true, created: true, replayed: false, message_id: 'm' });
  await send;
  assert.deepEqual(h.events, before);
  assert.ok(!h.events.includes('invalidate'));
});

test('creation uses principal and workspace captured before the workspace-save await', async () => {
  const h = harness();
  const pending = deferred();
  let args;
  h.client.sendMessage = () => pending.promise;
  h.client.createAgentConversation = async (...value) => {
    args = value;
    return { id: 'created', project_id: 'p' };
  };
  const send = h.hook.sendMessageContent('hello', []);
  h.params.auth.user.user_id = 'mutated-user';
  h.params.dataset.workspaces.push({ id: 'w', name: 'mutated-workspace' });
  pending.resolve({ id: 'm', mentions: ['agent'] }); // Saved mention-only path does not create.
  await send;
  assert.equal(args, undefined);
  h.params.auth.user.user_id = 'u';
  h.params.dataset.workspaces = [];
  const waiting = deferred();
  h.client.sendMessage = () => waiting.promise;
  const second = h.hook.sendMessageContent('hello', []);
  h.params.auth.user.user_id = 'mutated-user';
  h.params.dataset.workspaces.push({ id: 'w', name: 'mutated-workspace' });
  waiting.resolve({ id: 'm2', mentions: [] });
  await second;
  assert.equal(args[2], 'u');
  assert.equal(args[0], 'Desktop workspace: hello');
});

test('acknowledged RunInput clears only its own retry key and publishes ordered inputs', async () => {
  const h = harness();
  const pending = deferred();
  h.state.inputs = [{ id: 'later', sequence: 3 }];
  h.render({
    selectedConversation: { id: 'c', project_id: 'p' },
    currentArtifactRun: { id: 'r', conversation_id: 'c', revision: 2, status: 'running' },
    runInputDelivery: 'queue_next',
    runInputDeliveryOptions: ['queue_next'],
    sessionRunInputOperationsV2: {
      createRunInput() {
        return pending.promise;
      },
    },
  });
  const send = h.hook.sendMessageContent('hello', [], () => h.events.push('clear'));
  const newer = { signature: 'newer', messageId: 'newer', idempotencyKey: 'newer' };
  h.params.runInputRequestRef.current = newer;
  pending.resolve({
    input: { id: 'i', sequence: 1 },
    conversation_id: 'c',
    message_id: 'm',
    delivery_mode: 'queue_next',
  });
  await send;
  assert.equal(h.params.runInputRequestRef.current, newer);
  assert.deepEqual(
    h.state.inputs.map((item) => item.id),
    ['i', 'later'],
  );
  assert.ok(h.events.includes('clear'));
  assert.ok(h.events.includes('timeline-load'));
});

for (const mismatch of ['user_id', 'tenant_id', 'workspace_id']) {
  test(`cached conversation ${mismatch} mismatch fails before socket dispatch`, async () => {
    const h = harness();
    const conversation = {
      id: 'cached',
      project_id: 'p',
      tenant_id: 't',
      user_id: 'u',
      workspace_id: 'w',
      [mismatch]: 'previous-context',
    };
    h.render({
      config: { ...h.params.config, mode: mismatch === 'user_id' ? 'cloud' : 'local' },
      localRuntimeMode: mismatch !== 'user_id',
      agentConversationSession: { scopeKey: 'p::w', conversation },
    });
    h.params.socket.sendAgentMessage = () => {
      h.events.push('socket');
      return true;
    };
    await h.hook.sendMessageContent('hello', []);
    assert.ok(!h.events.includes('socket'), `cached ${mismatch} mismatch reached socket`);
    assert.ok(!h.events.includes('run'));
    assert.ok(h.state.error);
  });
}

test('Local ordinary conversation sentinel user_id remains compatible with its real projection', async () => {
  const h = harness();
  h.render({
    agentConversationSession: {
      scopeKey: 'p::w',
      conversation: {
        id: 'cached',
        project_id: 'p',
        tenant_id: 't',
        workspace_id: 'w',
        user_id: 'local-user',
      },
    },
  });
  h.params.socket.sendAgentMessage = () => {
    h.events.push('socket');
    return true;
  };
  await h.hook.sendMessageContent('hello', []);
  assert.ok(h.events.includes('socket'));
  assert.equal(h.state.error, null);
});

test('an observed principal change rejects the same Local cache until replacement or clearing', async () => {
  const h = harness();
  const session = {
    scopeKey: 'p::w',
    conversation: {
      id: 'cached',
      project_id: 'p',
      tenant_id: 't',
      workspace_id: 'w',
      user_id: 'local-user',
    },
  };
  h.render({ agentConversationSession: session });
  h.params.socket.sendAgentMessage = () => {
    h.events.push('socket');
    return true;
  };
  await h.hook.sendMessageContent('before', []);
  assert.ok(h.events.includes('socket'));
  h.events.length = 0;
  h.render({ auth: { user: { user_id: 'next-user' } } });
  await h.hook.sendMessageContent('after', []);
  assert.ok(!h.events.includes('socket'));
  assert.ok(h.state.error);
  h.render();
  h.events.length = 0;
  await h.hook.sendMessageContent('still-stale', []);
  assert.ok(!h.events.includes('socket'));
  h.render({ agentConversationSession: { ...session, conversation: { ...session.conversation } } });
  h.events.length = 0;
  await h.hook.sendMessageContent('replacement', []);
  assert.ok(h.events.includes('socket'));
  assert.equal(h.state.error, null);
  h.render({ auth: { user: { user_id: 'third-user' } } });
  h.render({ agentConversationSession: null });
  h.render({ agentConversationSession: session });
  h.events.length = 0;
  await h.hook.sendMessageContent('after-clear', []);
  assert.ok(h.events.includes('socket'));
});
