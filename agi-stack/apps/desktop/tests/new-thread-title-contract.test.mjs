import assert from 'node:assert/strict';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const compiled = '/tmp/agistack-desktop-test-dist/apps/desktop/src';
const { DesktopApiClient } = require(`${compiled}/api/client.js`);

function loadConversationThreads() {
  const source = new URL('../src/hooks/useConversationThreads.ts', import.meta.url);
  const module = { exports: {} };
  const code = ts.transpileModule(readFileSync(source, 'utf8'), {
    fileName: source.pathname,
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  new Function('require', 'module', 'exports', code)(
    (name) => {
      if (name === '../i18n') return { useI18n: () => ({ t: (key) => key }) };
      if (name === '../appShellTypes') {
        return { agentConversationScopeKeyFor: (...parts) => parts.join('\u0000') };
      }
      const path = new URL(name + '.js', source).pathname.split('/src/')[1];
      return require(`${compiled}/${path}`);
    },
    module,
    module.exports,
  );
  return module.exports.useConversationThreads;
}

const useConversationThreads = loadConversationThreads();

for (const [name, prompt, wrongOwner] of [
  ['space at the truncation boundary', `${'a'.repeat(95)} remaining neutral request`, false],
  ['first line with surrounding whitespace', '  中性浏览器验收  \nsecond line', false],
  ['cross-owner response remains rejected', `${'a'.repeat(95)} remaining request`, true],
]) {
  test(`new-thread create preserves the strict title contract: ${name}`, async () => {
    const received = [];
    const messages = [];
    const errors = [];
    const server = createServer(async (request, response) => {
      assert.equal(request.method, 'POST');
      assert.equal(request.url, '/api/v1/agent/conversations');
      let raw = '';
      for await (const chunk of request) raw += chunk;
      const body = JSON.parse(raw);
      received.push(body);
      response.setHeader('Content-Type', 'application/json');
      response.writeHead(201).end(
        JSON.stringify({
          id: 'owned-conversation',
          tenant_id: 'tenant',
          project_id: body.project_id,
          user_id: wrongOwner ? 'other-user' : 'user',
          title: body.title.trim(),
          status: 'active',
          workspace_id: null,
          message_count: 0,
          created_at: '2026-10-29T00:00:00Z',
          agent_config: body.agent_config,
        }),
      );
    });
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    const previousWindow = globalThis.window;
    globalThis.window = { setTimeout: () => 1, clearTimeout() {} };
    try {
      const config = {
        mode: 'cloud',
        apiBaseUrl: `http://127.0.0.1:${server.address().port}`,
        apiKey: 'owned-fixture',
        localApiToken: '',
        tenantId: 'tenant',
        projectId: 'project',
        workspaceId: '',
      };
      const client = new DesktopApiClient(config);
      const pending = new Map();
      const noop = () => {};
      let dataset = { conversationsByWorkspace: {} };
      const hook = useConversationThreads({
        auth: { user: { user_id: 'user' } },
        config,
        configRef: { current: config },
        connection: 'ready',
        contextRevisionRef: { current: 1 },
        configScopeEpochRef: { current: 1 },
        pendingNewTaskAgentTurnsRef: { current: pending },
        newThreadCreationClientV2: { bindOperation: () => client },
        commitRuntimeConfig: noop,
        setNewThreadCreating: noop,
        setNewThreadError: (value) => errors.push(value),
        setError: noop,
        setSelectedTaskId: noop,
        resetConversationTimeline: noop,
        setAgentTaskSignals: noop,
        setSectionBackStack: noop,
        setSectionForwardStack: noop,
        setDataset: (update) => {
          dataset = update(dataset);
        },
        setAgentConversationSession: noop,
        applySectionSideEffects: noop,
        loadConversationTimeline: async () => {},
        upsertAgentTaskSignal: noop,
        socket: {
          sendAgentMessage: (message) => {
            messages.push(message);
            pending.get(message.messageId).resolve('acknowledged');
            return true;
          },
        },
      });
      await hook.createComposerThread({
        prompt,
        mode: 'work',
        workspaceId: '',
        model: null,
        contextItems: [],
      });
      assert.equal(received.length, 1);
      assert.equal(received[0].title, prompt.split(/\r?\n/, 1)[0].trim().slice(0, 96).trim());
      assert.equal(messages.length, wrongOwner ? 0 : 1);
      assert.equal(errors.at(-1), wrongOwner ? 'Invalid agent conversation response' : null);
      if (!wrongOwner) assert.equal(messages[0].displayContent, prompt);
    } finally {
      globalThis.window = previousWindow;
      await new Promise((resolve) => server.close(resolve));
    }
  });
}
