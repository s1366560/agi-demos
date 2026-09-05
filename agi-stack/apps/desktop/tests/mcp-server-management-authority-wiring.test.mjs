import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { webcrypto } from 'node:crypto';

const require = createRequire(import.meta.url);
const ts = require('typescript');

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

// Compile the complete production hook and its pure dependencies in memory.
// The harness controls React state/effect lifetime, never the mutation callbacks.
function loadHook(react) {
  const cache = new Map();
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const module = { exports: {} };
    cache.set(url.href, module.exports);
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    }).outputText;
    new Function('require', 'module', 'exports', 'crypto', code)(
      (name) => {
        if (name === 'react') return react;
        assert.ok(name.startsWith('./'), `Unexpected runtime dependency: ${name}`);
        return load(new URL(`${name}.ts`, url));
      },
      module,
      module.exports,
      webcrypto,
    );
    return module.exports;
  }
  return load(new URL('../src/features/settings/useMCPServerManagement.ts', import.meta.url))
    .useMCPServerManagement;
}

function harness(mode = 'local') {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const equal = (left, right) =>
    left &&
    right &&
    left.length === right.length &&
    left.every((item, index) => Object.is(item, right[index]));
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { value: initial };
      return [
        slots[index].value,
        (value) => {
          slots[index].value = typeof value === 'function' ? value(slots[index].value) : value;
        },
      ];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback(callback, dependencies) {
      const index = cursor++;
      if (!equal(slots[index]?.dependencies, dependencies)) {
        slots[index] = { dependencies, callback };
      }
      return slots[index].callback;
    },
    useEffect(effect, dependencies) {
      const index = cursor++;
      if (!equal(slots[index]?.dependencies, dependencies)) {
        effects.push(() => {
          slots[index]?.cleanup?.();
          slots[index] = { dependencies, cleanup: effect() };
        });
      }
    },
  };
  const provision = deferred();
  const entered = deferred();
  const calls = { provision: [], create: [], update: [], toggle: [], remove: [], list: [] };
  const client = {
    async provisionMCPServerCredential(input) {
      calls.provision.push(input);
      entered.resolve();
      return provision.promise;
    },
    async createMCPServer(input) {
      calls.create.push(input);
    },
    async updateMCPServer(id, input) {
      calls.update.push({ id, ...input });
    },
    async setMCPServerEnabled(id, input) {
      calls.toggle.push({ id, ...input });
    },
    async deleteMCPServer(id, input) {
      calls.remove.push({ id, ...input });
    },
    async listMCPServers(projectId) {
      calls.list.push(projectId);
      return [];
    },
  };
  let props = {
    client,
    active: false,
    canManage: true,
    contextKey: 'context-one',
    config: { mode, tenantId: 'tenant-one', projectId: 'project-one' },
  };
  const hook = loadHook(react);
  function render(next = {}) {
    props = { ...props, ...next };
    cursor = 0;
    effects = [];
    const value = hook(props);
    for (const effect of effects) effect();
    return value;
  }
  render();
  return {
    render,
    calls,
    provision,
    entered,
    switchContext() {
      render({ contextKey: 'context-two', config: { ...props.config, projectId: 'project-two' } });
    },
    unmount() {
      for (const slot of slots) slot?.cleanup?.();
    },
  };
}

const server = {
  id: 'server-one',
  tenant_id: 'tenant-one',
  project_id: 'project-one',
  name: 'existing',
  server_type: 'http',
  enabled: true,
  runtime_status: 'running',
  runtime_metadata: { revision: 7 },
  transport_config: { url: 'https://mcp.example/old' },
};
const submission = {
  name: 'changed',
  serverType: 'http',
  transport: { url: 'https://mcp.example/new' },
  credential: { kind: 'header', name: 'Authorization', secret: 'synthetic-test-secret' },
};

for (const operation of ['create', 'update']) {
  for (const interruption of ['switchContext', 'unmount']) {
    test(`${operation} stops after provisioning when ${interruption} invalidates its context`, async () => {
      const instance = harness();
      const initial = instance.render();
      if (operation === 'create') initial.openCreate();
      else initial.openEdit(server);
      const pending = instance.render()[operation](submission);
      await instance.entered.promise;
      instance[interruption]();
      instance.provision.resolve({
        stored: true,
        credential_kind: 'header',
        credential_name: 'Authorization',
        duplicate: false,
      });
      await pending;
      assert.equal(instance.calls.provision.length, 1);
      assert.deepEqual(instance.calls.create, []);
      assert.deepEqual(instance.calls.update, []);
      assert.deepEqual(instance.calls.list, []);
    });
  }

  test(`${operation} in the same context binds the mutation to provisioning without its secret`, async () => {
    const instance = harness();
    const initial = instance.render();
    if (operation === 'create') initial.openCreate();
    else initial.openEdit(server);
    const pending = instance.render()[operation](submission);
    await instance.entered.promise;
    instance.provision.resolve({
      stored: true,
      credential_kind: 'header',
      credential_name: 'Authorization',
      duplicate: false,
    });
    await pending;
    const [mutation] = instance.calls[operation];
    assert.equal(instance.calls[operation].length, 1);
    assert.equal(mutation.project_id, 'project-one');
    assert.equal(mutation.idempotency_key, instance.calls.provision[0].mutation_idempotency_key);
    assert.deepEqual(mutation.transport_config, {
      url: submission.transport.url,
      credential_header_names: ['Authorization'],
    });
    assert.ok(!JSON.stringify(mutation).includes(submission.credential.secret));
    assert.equal(instance.calls.provision[0].secret, submission.credential.secret);
    if (operation === 'update') assert.equal(mutation.expected_revision, 7);
    assert.deepEqual(instance.calls.list, ['project-one']);
  });
}

for (const operation of ['toggle', 'remove']) {
  test(`Cloud ${operation} accepts a server without inventing a revision`, async () => {
    const instance = harness('cloud');
    const target = { ...server, runtime_metadata: {} };
    if (operation === 'toggle') await instance.render().toggleServer(target);
    else {
      instance.render().openEdit(target);
      await instance.render().remove();
    }
    assert.equal(instance.calls[operation].length, 1);
    assert.equal(Object.hasOwn(instance.calls[operation][0], 'expected_revision'), false);
    assert.equal(instance.calls[operation][0].project_id, 'project-one');
  });

  test(`Local ${operation} refuses a server whose revision is absent`, async () => {
    const instance = harness();
    const target = { ...server, runtime_metadata: {} };
    if (operation === 'toggle') await instance.render().toggleServer(target);
    else {
      instance.render().openEdit(target);
      await instance.render().remove();
    }
    assert.deepEqual(instance.calls[operation], []);
    const result = instance.render();
    assert.equal(
      operation === 'toggle' ? result.error : result.dialogError,
      'MCP server revision is unavailable',
    );
  });
}
