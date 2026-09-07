import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const cache = new Map();
const transpile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
function load(url) {
  if (cache.has(url.href)) return cache.get(url.href);
  const module = { exports: {} };
  cache.set(url.href, module.exports);
  new Function('require', 'module', 'exports', transpile(readFileSync(url, 'utf8')))(
    (name) => (name.startsWith('.') ? load(new URL(`${name}.ts`, url)) : require(name)),
    module,
    module.exports,
  );
  return module.exports;
}
const { executeVaultBoundCloudRequest: execute } = load(
  new URL('../electron/main/cloudRequestPolicy.ts', import.meta.url),
);
const { RendererDeliveryAdmissionV2 } = load(
  new URL('../electron/main/rendererDeliveryAdmissionV2.ts', import.meta.url),
);
const mainSource = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const preloadSource = readFileSync(
  new URL('../electron/preload/index.ts', import.meta.url),
  'utf8',
);
const mainAst = ts.createSourceFile('index.ts', mainSource, ts.ScriptTarget.Latest, true);
const preloadAst = ts.createSourceFile('preload.ts', preloadSource, ts.ScriptTarget.Latest, true);
function nodes(root, predicate) {
  const result = [];
  const visit = (node) => {
    if (predicate(node)) result.push(node);
    ts.forEachChild(node, visit);
  };
  visit(root);
  return result;
}
function fn(ast, name) {
  return nodes(ast, (node) => ts.isFunctionDeclaration(node) && node.name?.text === name)[0];
}
function compileFunction(source, bindings, name) {
  if (bindings.sandboxDesktopGrants) {
    bindings = {
      ...bindings,
      rendererDeliveryAdmissionV2: new RendererDeliveryAdmissionV2(),
      rendererDeliveryOwnersV2: new Map(),
    };
    source = `${fn(mainAst, 'withDesktopAuthorityTransitionV2').getText(mainAst)}
      ${fn(mainAst, 'retireRendererDeliveryOwnerV2').getText(mainAst)}
${source}`;
  }
  return new Function(...Object.keys(bindings), `${transpile(source)};return ${name};`)(
    ...Object.values(bindings),
  );
}
function expression(node, bindings) {
  return compileFunction(`const result = ${node.getText()};`, bindings, 'result');
}
function commandCase(name, bindings) {
  const handler = fn(mainAst, 'executeDesktopCommand');
  const clause = nodes(
    handler,
    (node) => ts.isCaseClause(node) && node.expression.text === name,
  )[0];
  assert.ok(clause, `actual main case ${name}`);
  return compileFunction(
    `async function invoke(event,args){${clause.statements.map((node) => node.getText()).join('\n')}}`,
    bindings,
    'invoke',
  );
}
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const request = () => ({
  path: '/api/v1/workspace-context/switch',
  method: 'POST',
  body: {
    tenant_id: 'tenant-one',
    project_id: 'project-two',
    expected_revision: 1,
    idempotency_key: 'context-switch-fixture',
  },
});
function fixture(overrides = {}) {
  const events = [];
  const dependencies = {
    loadTrustedSession: async () => ({
      version: 1,
      api_base_url: 'https://cloud.example',
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: 'synthetic-integration-credential',
      expires_at: null,
    }),
    fetch: async (url, init) => {
      events.push(init.method);
      return new Response(
        JSON.stringify({
          context: { tenant_id: 'tenant-one', project_id: 'project-one', workspace_id: null },
        }),
        { headers: { 'content-type': 'application/json' } },
      );
    },
    ...overrides,
  };
  return { events, dependencies };
}

test('actual context-switch request awaits grant revocation after live scope observation and before POST', async () => {
  const gate = deferred(),
    entered = deferred();
  const f = fixture();
  f.dependencies.withContextSwitch = async (operation) => {
    f.events.push('revoke-start');
    entered.resolve();
    await gate.promise;
    f.events.push('revoke-end');
    try {
      return await operation();
    } finally {
      f.events.push('barrier-released');
    }
  };
  const pending = execute(request(), f.dependencies);
  await entered.promise;
  assert.deepEqual(f.events, ['GET', 'revoke-start']);
  gate.resolve();
  assert.equal((await pending).status, 200);
  assert.deepEqual(f.events, ['GET', 'revoke-start', 'revoke-end', 'POST', 'barrier-released']);
});
test('failed or cross-tenant live scope observation cannot revoke grants or POST', async () => {
  for (const [status, tenant] of [
    [403, 'tenant-one'],
    [200, 'other-tenant'],
  ]) {
    let revoke = 0,
      posts = 0;
    const f = fixture({
      withContextSwitch: async () => {
        revoke++;
      },
      fetch: async (_url, init) => {
        if (init.method === 'POST') posts++;
        return new Response(
          JSON.stringify({
            context: { tenant_id: tenant, project_id: 'project-one', workspace_id: null },
          }),
          { status },
        );
      },
    });
    await assert.rejects(execute(request(), f.dependencies));
    assert.equal(revoke, 0);
    assert.equal(posts, 0);
  }
});
test('failed grant cleanup preserves its error and prevents context-switch POST', async () => {
  const primary = new Error('grant cleanup did not complete');
  const f = fixture({
    withContextSwitch: async () => {
      throw primary;
    },
  });
  await assert.rejects(execute(request(), f.dependencies), (error) => error === primary);
  assert.deepEqual(f.events, ['GET']);
});
test('cancellation during awaited revocation prevents POST and pre-cancel performs no fetch', async () => {
  const gate = deferred(),
    entered = deferred(),
    abort = new AbortController();
  const f = fixture({
    signal: abort.signal,
    withContextSwitch: async (operation) => {
      entered.resolve();
      await gate.promise;
      return operation();
    },
  });
  const pending = execute(request(), f.dependencies);
  await entered.promise;
  abort.abort();
  gate.resolve();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.deepEqual(f.events, ['GET']);
  const second = fixture({ signal: abort.signal });
  await assert.rejects(execute(request(), second.dependencies), { name: 'AbortError' });
  assert.deepEqual(second.events, []);
});
test('preload forwards grant IPC only through its real command allowlist and never exposes vault load/save', async () => {
  const allowed = nodes(
    preloadAst,
    (node) => ts.isVariableDeclaration(node) && node.name.getText() === 'allowedCommands',
  )[0];
  const calls = [];
  const invoke = compileFunction(
    `const DESKTOP_COMMAND_CHANNEL='agistack:desktop-command';const ${allowed.getText()};\n${fn(preloadAst, 'invokeDesktopCommand').getText()}`,
    {
      ipcRenderer: {
        invoke: async (...args) => {
          calls.push(args);
          return 'opaque';
        },
      },
    },
    'invokeDesktopCommand',
  );
  for (const command of ['sandbox_desktop_grant_open', 'sandbox_desktop_grant_close'])
    assert.equal(await invoke(command, { requestId: 'opaque-request' }), 'opaque');
  assert.deepEqual(
    calls.map((call) => call[1]),
    ['sandbox_desktop_grant_open', 'sandbox_desktop_grant_close'],
  );
  for (const command of ['trusted_session_load', 'trusted_session_save'])
    await assert.rejects(invoke(command));
  assert.equal(calls.length, 2);
});
test('actual grant IPC cases require trusted main-frame owner and pass its real frameTreeNodeId', async () => {
  const frame = { frameTreeNodeId: 33, url: 'trusted-renderer' },
    contents = { id: 7, mainFrame: null };
  contents.mainFrame = frame;
  const authorize = compileFunction(
    fn(mainAst, 'authorizedCloudRequestOwner').getText(),
    {
      mainWindow: { isDestroyed: () => false, webContents: contents },
      rendererDevelopmentUrl: () => null,
      isTrustedNativeFileFrameUrl: (url) => url === 'trusted-renderer',
    },
    'authorizedCloudRequestOwner',
  );
  const calls = [],
    gate = deferred();
  const bindings = {
    authorizedCloudRequestOwner: authorize,
    sandboxDesktopGrants: {
      open: async (...args) => {
        calls.push(['open', ...args]);
        return { grantId: 'opaque' };
      },
      close: async (...args) => {
        calls.push(['close', ...args]);
        await gate.promise;
      },
    },
  };
  const event = { sender: contents, senderFrame: frame },
    args = { requestId: 'request' };
  assert.deepEqual(await commandCase('sandbox_desktop_grant_open', bindings)(event, args), {
    grantId: 'opaque',
  });
  assert.deepEqual(calls[0], ['open', 7, 33, args]);
  let closed = false;
  const closing = commandCase('sandbox_desktop_grant_close', bindings)(event, args).then(() => {
    closed = true;
  });
  await Promise.resolve();
  assert.equal(closed, false);
  gate.resolve();
  await closing;
  await assert.rejects(
    commandCase('sandbox_desktop_grant_open', bindings)(
      { ...event, senderFrame: { ...frame } },
      args,
    ),
  );
  assert.equal(calls.length, 2);
});
test('password/OAuth vault replacement and logout callbacks await revocation before actual sidecar mutation', async () => {
  for (const constructor of [
    'DesktopCloudAuthenticationAuthority',
    'DesktopOAuthCallbackAuthority',
  ]) {
    const call = nodes(
      mainAst,
      (node) => ts.isNewExpression(node) && node.expression.getText() === constructor,
    )[0];
    assert.ok(call);
    for (const key of constructor === 'DesktopCloudAuthenticationAuthority'
      ? ['saveTrustedSession', 'clearTrustedSession']
      : ['saveTrustedSession']) {
      const property = call.arguments[0].properties.find((node) => node.name?.getText() === key);
      assert.ok(property);
      const gate = deferred(),
        events = [];
      const callback = expression(property.initializer, {
        sandboxDesktopGrants: {
          withAuthorityTransition: async (operation) => {
            events.push('revoke');
            await gate.promise;
            return operation();
          },
        },
        applicationSupervisor: {
          invoke: async (command) => {
            events.push(command);
          },
        },
      });
      const pending = callback({ opaque: true });
      await new Promise(setImmediate);
      assert.deepEqual(events, ['revoke']);
      gate.resolve();
      await pending;
      assert.deepEqual(events, [
        'revoke',
        key === 'saveTrustedSession' ? 'trusted_session_save' : 'trusted_session_clear',
      ]);
      const primary = new Error('revoke failed');
      const blocked = expression(property.initializer, {
        sandboxDesktopGrants: {
          withAuthorityTransition: async (operation) => {
            throw primary;
          },
        },
        applicationSupervisor: { invoke: () => assert.fail('mutation after failed revoke') },
      });
      await assert.rejects(blocked({}), (error) => error === primary);
    }
  }
});
test('actual sidecar default branch revokes before local-session replacement clear and authority select', async () => {
  const clause = nodes(fn(mainAst, 'executeDesktopCommand'), ts.isDefaultClause)[0];
  const commands = [
    'trusted_session_clear',
    'local_trusted_session_save',
    'local_trusted_session_clear',
    'platform_plugin_authority_select_v2',
  ];
  for (const command of commands) {
    const gate = deferred(),
      events = [];
    const invoke = compileFunction(
      `async function invoke(command,args){${clause.statements.map((node) => node.getText()).join('\n')}}`,
      {
        SIDECAR_COMMANDS: new Set(commands),
        sandboxDesktopGrants: {
          withAuthorityTransition: async (operation) => {
            events.push('revoke');
            await gate.promise;
            return operation();
          },
        },
        sidecarSupervisor: {
          invoke: async (name) => {
            events.push(name);
          },
        },
      },
      'invoke',
    );
    const pending = invoke(command, {});
    await new Promise(setImmediate);
    assert.deepEqual(events, ['revoke']);
    gate.resolve();
    await pending;
    assert.deepEqual(events, ['revoke', command]);
  }
});
test('main cloud-request path injects its real revoke callback and releases the IPC request lease', async () => {
  const events = [];
  const callback = commandCase('cloud_request', {
    authorizedCloudRequestOwner: () => 7,
    sidecarSupervisor: { invoke() {} },
    net: { fetch() {} },
    cloudRequestExecutions: {
      begin: () => ({
        signal: new AbortController().signal,
        release: () => events.push('release'),
      }),
    },
    sandboxDesktopGrants: {
      withAuthorityTransition: async (operation) => {
        events.push('revoke');
        return operation();
      },
    },
    executeVaultBoundCloudRequest: async (_request, deps) => {
      return deps.withContextSwitch(async () => {
        events.push('execute');
        return { status: 200 };
      });
    },
  });
  assert.deepEqual(await callback({}, { requestId: 'opaque', request: request() }), {
    status: 200,
  });
  assert.deepEqual(events, ['revoke', 'execute', 'release']);
});

test('actual request broker and registry keep new grants blocked through blanking and pending POST response', async () => {
  const { SandboxDesktopGrantRegistry } = load(
    new URL('../electron/main/sandboxDesktopGrantRegistry.ts', import.meta.url),
  );
  const blank = deferred(),
    post = deferred(),
    postEntered = deferred();
  let authorizations = 0;
  const registry = new SandboxDesktopGrantRegistry({
    randomId: () => 'grant_fixture_0123456789',
    blankFrame: () => blank.promise,
    authorize: async () => {
      authorizations++;
      return {
        apiBaseUrl: 'https://cloud.example',
        credential: 'synthetic-integration-credential',
        expiresAt: null,
      };
    },
  });
  const grantInput = {
    requestId: 'request_first_0123456789',
    tenantId: 'tenant-one',
    projectId: 'project-one',
    descriptor: {
      contract_version: 1,
      project_id: 'project-one',
      protocol: 'kasmvnc-1',
      auth_mode: 'scoped_http_only_cookie',
      proxy_url: '/api/v1/projects/project-one/sandbox/desktop/proxy/vnc.html',
    },
  };
  const first = await registry.open(7, 11, grantInput);
  assert.equal(
    registry.beforeRequest(
      {
        id: 1,
        webContentsId: 7,
        method: 'GET',
        resourceType: 'subFrame',
        url: first.frameUrl,
        frame: { frameTreeNodeId: 12, parentFrameTreeNodeId: 11, name: first.frameName },
      },
      {},
    ).kind,
    'authorized',
  );
  registry.completeRequest(1);
  const f = fixture({
    withContextSwitch: (operation) => registry.withAuthorityTransition(operation),
  });
  const fetch = f.dependencies.fetch;
  f.dependencies.fetch = async (url, init) => {
    if (init.method === 'POST') {
      postEntered.resolve();
      await post.promise;
    }
    return fetch(url, init);
  };
  const switching = execute(request(), f.dependencies);
  // Wait for actual live observation to enter the transition, without releasing blanking.
  while (f.events.length === 0) await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const next = { ...grantInput, requestId: 'request_second_0123456789' };
  await assert.rejects(registry.open(7, 11, next), /authority_transition/);
  assert.equal(authorizations, 1);
  blank.resolve();
  await postEntered.promise;
  await assert.rejects(registry.open(7, 11, next), /authority_transition/);
  assert.equal(authorizations, 1);
  post.resolve();
  await switching;
  await registry.open(7, 11, next);
  assert.equal(authorizations, 2);
  await registry.revokeAll();
});
