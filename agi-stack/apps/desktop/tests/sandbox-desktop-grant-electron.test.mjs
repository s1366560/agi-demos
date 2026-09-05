import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { EventEmitter } from 'node:events';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  installSandboxDesktopGrantElectron: install,
  blankSandboxDesktopGrantFrame: blank,
} = require('/tmp/agistack-desktop-test-dist/electron/main/sandboxDesktopGrantElectron.js');
function fixture() {
  const listeners = {};
  const session = {
    webRequest: Object.fromEntries(
      ['onBeforeSendHeaders', 'onHeadersReceived', 'onCompleted', 'onErrorOccurred'].map((name) => [
        name,
        (listener) => {
          listeners[name] = listener;
        },
      ]),
    ),
  };
  const main = { frameTreeNodeId: 11, framesInSubtree: [] };
  const frame = {
    frameTreeNodeId: 12,
    parent: main,
    name: 'memstack-kasm-grant_0123456789',
    url: '',
    isDestroyed: () => false,
  };
  main.framesInSubtree = [main, frame];
  const owner = Object.assign(new EventEmitter(), {
    session,
    mainFrame: main,
    isDestroyed: () => false,
  });
  const calls = { navigate: [], destroy: [], before: [], complete: [], revoke: [] };
  const registry = {
    beforeRequest: (details, headers) => {
      calls.before.push(details);
      return { kind: 'authorized', requestHeaders: { ...headers, Authorization: 'fixture' } };
    },
    responseHeaders: (_details, headers) =>
      Object.fromEntries(Object.entries(headers).filter(([key]) => key !== 'Set-Cookie')),
    observeFrameNavigation: (...args) => calls.navigate.push(args),
    observeFrameDestroyed: (...args) => calls.destroy.push(args),
    completeRequest: (id) => calls.complete.push(id),
    revokeOwner: async (id) => {
      calls.revoke.push(id);
    },
  };
  return {
    session,
    listeners,
    main,
    frame,
    owner,
    calls,
    registry,
    resolveOwner: (id) => (id === 7 ? owner : undefined),
  };
}
test('one Session listener set projects real frame fields and observes navigation outside proxy filter', () => {
  const f = fixture();
  const installed = install(f.session, f.registry, { resolveOwner: f.resolveOwner });
  try {
    assert.equal(install(f.session, f.registry, { resolveOwner: f.resolveOwner }), installed);
    assert.throws(() => install(f.session, {}, { resolveOwner: f.resolveOwner }));
    let result;
    f.listeners.onBeforeSendHeaders(
      {
        id: 1,
        url: 'https://cloud.invalid/vnc.html',
        method: 'GET',
        resourceType: 'subFrame',
        webContentsId: 7,
        frame: f.frame,
        requestHeaders: {},
      },
      (value) => {
        result = value;
      },
    );
    assert.equal(result.requestHeaders.Authorization, 'fixture');
    assert.deepEqual(f.calls.before[0].frame, {
      frameTreeNodeId: 12,
      parentFrameTreeNodeId: 11,
      name: f.frame.name,
    });
    f.owner.emit('did-start-navigation', { url: 'https://other.invalid', frame: f.frame });
    assert.deepEqual(f.calls.navigate.at(-1), [7, 12, 'https://other.invalid']);
    f.listeners.onCompleted({ id: 1 });
    assert.deepEqual(f.calls.complete, [1]);
  } finally {
    installed.dispose();
  }
  assert.equal(f.listeners.onBeforeSendHeaders, null);
});
test('destroyed frame snapshots cannot fall back to owner-only authentication', () => {
  const f = fixture();
  f.frame.isDestroyed = () => true;
  const installed = install(f.session, f.registry, { resolveOwner: f.resolveOwner });
  try {
    f.listeners.onBeforeSendHeaders(
      {
        id: 2,
        url: 'https://cloud.invalid/a.js',
        method: 'GET',
        resourceType: 'script',
        webContentsId: 7,
        frame: f.frame,
        requestHeaders: {},
      },
      () => {},
    );
    assert.equal(f.calls.before[0].frame, null);
  } finally {
    installed.dispose();
  }
});
test('blank waits until exact bound-frame script executes and actual frame becomes blank', async () => {
  const f = fixture();
  f.frame.url = 'https://cloud.invalid/vnc.html';
  let execute;
  const executing = new Promise((resolve) => {
    execute = resolve;
  });
  f.frame.executeJavaScript = async (script) => {
    assert.equal(script, 'window.location.replace("about:blank")');
    await executing;
    f.frame.url = 'about:blank';
  };
  let done = false;
  const closing = blank(f.resolveOwner, 7, 12).then(() => {
    done = true;
  });
  await Promise.resolve();
  assert.equal(done, false);
  execute();
  await closing;
  assert.equal(done, true);
});
test('an already blank frame still receives cancellation of pending navigation and no main frame can be blanked', async () => {
  const f = fixture();
  f.frame.url = 'about:blank';
  let scripts = 0;
  f.frame.executeJavaScript = async () => {
    scripts++;
  };
  await blank(f.resolveOwner, 7, 12);
  assert.equal(scripts, 1);
  await assert.rejects(blank(f.resolveOwner, 7, 11), /frame_mismatch/);
  f.main.framesInSubtree = [f.main];
  await blank(f.resolveOwner, 7, 12);
  assert.equal(scripts, 1);
});

test('same-name rejected sibling cannot prevent closing the exact bound frame', async () => {
  const f = fixture();
  f.frame.url = 'https://cloud.invalid/vnc.html';
  const sibling = { ...f.frame, frameTreeNodeId: 13 };
  f.main.framesInSubtree.push(sibling);
  f.main.executeJavaScript = () => assert.fail('name-based parent lookup is not a frame identity');
  sibling.executeJavaScript = () => assert.fail('sibling must never be navigated');
  f.frame.executeJavaScript = async () => {
    f.frame.url = 'about:blank';
  };
  await blank(f.resolveOwner, 7, 12);
  assert.equal(f.frame.url, 'about:blank');
  assert.equal(sibling.url, 'https://cloud.invalid/vnc.html');
});
