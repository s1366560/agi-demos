import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url),
  ts = require('typescript');
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
const { DesktopCloudAuthenticationAuthority } = load(
  new URL('../electron/main/cloudAuthenticationAuthority.ts', import.meta.url),
);
const { SandboxDesktopGrantRegistry } = load(
  new URL('../electron/main/sandboxDesktopGrantRegistry.ts', import.meta.url),
);
const source = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const ast = ts.createSourceFile('index.ts', source, ts.ScriptTarget.Latest, true);
function nodes(predicate) {
  const found = [];
  function visit(node) {
    if (predicate(node)) found.push(node);
    ts.forEachChild(node, visit);
  }
  visit(ast);
  return found;
}
const constructor = nodes(
  (node) =>
    ts.isNewExpression(node) &&
    node.expression.getText(ast) === 'DesktopCloudAuthenticationAuthority',
)[0];
const quitCall = nodes(
  (node) =>
    ts.isCallExpression(node) &&
    node.expression.getText(ast) === 'app.on' &&
    node.arguments[0]?.getText(ast) === "'before-quit'",
)[0];
assert.ok(constructor);
assert.ok(quitCall);
const capturedSupervisor = nodes(
  (node) => ts.isVariableDeclaration(node) && node.name.getText(ast) === 'applicationSupervisor',
)[0];
assert.ok(capturedSupervisor);
assert.equal(capturedSupervisor.initializer.getText(ast), 'sidecarSupervisor');
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => (resolve = done));
  return { promise, resolve };
};
const tick = () => new Promise(setImmediate);

async function fixture(trustedDevice) {
  const events = [],
    clearGate = deferred(),
    blankGate = deferred(),
    quit = deferred();
  let vault = null;
  const supervisor = {
    async invoke(command, args) {
      if (command === 'trusted_session_save') {
        vault = args.input;
        events.push('vault-save');
        return;
      }
      if (command === 'trusted_session_clear') {
        events.push('vault-clear-start');
        await clearGate.promise;
        vault = null;
        events.push('vault-clear-done');
        return;
      }
      if (command === 'trusted_session_load') return vault;
      assert.fail(`unexpected command ${command}`);
    },
    async stop() {
      events.push('supervisor-stop');
    },
  };
  const registry = new SandboxDesktopGrantRegistry({
    authorize: async () => ({
      apiBaseUrl: 'https://cloud.test',
      credential: 'fixture-grant-credential',
    }),
    randomId: () => 'grant-fixture-0000000001',
    blankFrame: async () => {
      events.push('frame-blank-start');
      await blankGate.promise;
      events.push('frame-blank-done');
    },
  });
  const bindings = {
    DesktopCloudAuthenticationAuthority,
    supervisor,
    sandboxDesktopGrants: registry,
    net: {
      fetch: async () =>
        new Response(
          JSON.stringify({
            access_token: 'fixture-login-token',
            token_type: 'bearer',
            must_change_password: false,
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    },
    randomUUID: () => 'fixture-random-id',
    cloudRequestExecutions: {
      cancelAll() {
        events.push('request-cancel');
      },
    },
    app: {
      quit() {
        events.push('quit');
        quit.resolve();
      },
    },
  };
  // The actual main constructor and quit callback share these lexical bindings.
  // before-quit will set sidecarSupervisor=null exactly as it does in Electron.
  const code = `let sidecarSupervisor=supervisor;
 ${capturedSupervisor.parent.parent.getText(ast)}
 let cloudAuthenticationAuthority=${constructor.getText(ast)};
 let cloudSocketBroker=null,oauthCallbackAuthority=null,iabBackend=null,iabPool=null;
 let unsubscribeUpdateState=null,automaticUpdates=null,sidecarShutdownComplete=false;
 const authority=cloudAuthenticationAuthority;
 const beforeQuit=${quitCall.arguments[1].getText(ast)};
 return {authority,beforeQuit,supervisorIsNull:()=>sidecarSupervisor===null};`;
  const application = new Function(...Object.keys(bindings), transpile(code))(
    ...Object.values(bindings),
  );
  const result = await application.authority.loginWithPassword({
    apiBaseUrl: 'https://cloud.test',
    username: 'fixture@example.test',
    password: 'fixture-password',
    trustedDevice,
  });
  assert.deepEqual(result, { status: 'authenticated' });
  assert.ok(vault);
  const request = {
    requestId: 'request-fixture-0000001',
    tenantId: 'tenant',
    projectId: 'project',
    descriptor: {
      contract_version: 1,
      project_id: 'project',
      protocol: 'kasmvnc-1',
      auth_mode: 'scoped_http_only_cookie',
      proxy_url: '/api/v1/projects/project/sandbox/desktop/proxy/vnc.html',
    },
  };
  const grant = await registry.open(1, 10, request);
  assert.equal(
    registry.beforeRequest(
      {
        id: 1,
        url: grant.frameUrl,
        method: 'GET',
        resourceType: 'subFrame',
        webContentsId: 1,
        frame: { frameTreeNodeId: 11, parentFrameTreeNodeId: 10, name: grant.frameName },
      },
      {},
    ).kind,
    'authorized',
  );
  events.length = 0;
  return { events, application, clearGate, blankGate, quit, vault: () => vault };
}

test('nonpersistent native login actually clears the captured vault before stopping the supervisor on quit', async () => {
  const f = await fixture(false);
  f.application.beforeQuit({
    preventDefault() {
      f.events.push('prevent-default');
    },
  });
  assert.equal(f.application.supervisorIsNull(), true);
  await tick();
  assert.ok(f.events.includes('frame-blank-start'));
  assert.ok(!f.events.includes('vault-clear-start'));
  assert.ok(!f.events.includes('supervisor-stop'));
  f.blankGate.resolve();
  await tick();
  assert.ok(f.events.includes('vault-clear-start'));
  assert.ok(f.vault());
  assert.ok(!f.events.includes('supervisor-stop'));
  f.clearGate.resolve();
  await f.quit.promise;
  assert.equal(f.vault(), null);
  assert.ok(f.events.indexOf('frame-blank-done') < f.events.indexOf('vault-clear-start'));
  assert.ok(f.events.indexOf('vault-clear-done') < f.events.indexOf('supervisor-stop'));
  assert.ok(f.events.indexOf('supervisor-stop') < f.events.indexOf('quit'));
});

test('trusted-device persistence is preserved while quit still revokes frame grants before supervisor shutdown', async () => {
  const f = await fixture(true);
  f.application.beforeQuit({ preventDefault() {} });
  await tick();
  assert.ok(!f.events.includes('supervisor-stop'));
  f.blankGate.resolve();
  await f.quit.promise;
  assert.ok(f.vault());
  assert.ok(!f.events.includes('vault-clear-start'));
  assert.ok(f.events.indexOf('frame-blank-done') < f.events.indexOf('supervisor-stop'));
});
