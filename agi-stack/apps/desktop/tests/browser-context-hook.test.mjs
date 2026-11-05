import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const tick = () => new Promise(setImmediate);
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function fixture() {
  let effect, cleanup, recovery, nextTimer = 0;
  const timers = new Map(), calls = [], responses = [];
  const bridge = { activateContext: request => {
    calls.push(request);
    return responses.shift() ?? Promise.resolve({ session_id: request.conversation_id });
  } };
  const window = { __MEMSTACK_DESKTOP__: { iab: bridge, events: { onSidecarRecovered: listener => {
    recovery = listener; return () => { recovery = undefined; };
  } } } };
  const source = readFileSync(new URL('../src/features/browser/useBrowserContext.ts', import.meta.url), 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} };
  new Function('require', 'exports', 'window', 'setTimeout', 'clearTimeout', output)(
    () => ({ useEffect: callback => { effect = callback; } }), module.exports, window,
    (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    id => timers.delete(id),
  );
  return { calls, responses, timers,
    render: (config, id, authenticated = true) => { cleanup?.(); module.exports.useBrowserContext(config, id, authenticated); cleanup = effect(); },
    recover: () => recovery?.(), stop: () => cleanup?.(),
    retry: () => { const [id, timer] = timers.entries().next().value; timers.delete(id); timer.callback(); },
  };
}
const local = { mode: 'local', apiBaseUrl: 'http://localhost', apiKey: 'login-fixture', localApiToken: 'launch-fixture', tenantId: 'tenant', projectId: 'project' };

test('browser context follows authenticated selection and uses the login credential, never the launch token', async () => {
  const f = fixture(); f.render(local, 'chat-a'); await tick();
  assert.deepEqual(f.calls[0], { conversation_id: 'chat-a', mode: 'local', credential: 'login-fixture', tenant_id: 'tenant', project_id: 'project' });
  f.render(local, 'chat-b', false); await tick();
  assert.equal(f.calls.at(-1).conversation_id, null);
  f.stop();
});

test('cloud browser context leaves credential resolution in the native vault', async () => {
  const f = fixture(); f.render({ ...local, mode: 'cloud' }, 'cloud-chat'); await tick();
  assert.equal('credential' in f.calls[0], false);
  assert.equal(f.calls[0].conversation_id, 'cloud-chat'); f.stop();
});

test('failed selection retries, sidecar recovery cancels pending retry, and old completions cannot schedule another', async () => {
  const f = fixture(); const old = deferred(); f.responses.push(old.promise);
  f.render(local, 'old-chat');
  f.render(local, 'new-chat'); await tick();
  old.reject(new Error('old failed')); await tick();
  assert.equal(f.timers.size, 0);
  f.responses.push(Promise.reject(new Error('disconnected'))); f.recover(); await tick();
  assert.equal(f.timers.size, 1); assert.equal([...f.timers.values()][0].delay, 1000);
  f.recover(); await tick(); assert.equal(f.timers.size, 0);
  assert.equal(f.calls.at(-1).conversation_id, 'new-chat');
  f.stop(); assert.equal(f.calls.at(-1).conversation_id, null);
});

test('failed current activation retries without reviving a disposed selection', async () => {
  const f = fixture(); f.responses.push(Promise.reject(new Error('offline')));
  f.render(local, 'chat'); await tick(); f.retry(); await tick();
  assert.equal(f.calls.length, 2); assert.equal(f.calls[1].conversation_id, 'chat');
  f.responses.push(Promise.reject(new Error('offline'))); f.recover(); await tick();
  f.stop(); assert.equal(f.timers.size, 0);
  const before = f.calls.length; f.recover(); assert.equal(f.calls.length, before);
});
