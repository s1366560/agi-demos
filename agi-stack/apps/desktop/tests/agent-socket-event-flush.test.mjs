import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { scheduleAgentSocketEventFlush } = require('/tmp/agistack-desktop-test-dist/src/hooks/agentSocketEventFlush.js');

for (const scenario of ['frozen frame', 'frame wins', 'unmount']) {
  test(`socket event flush handles ${scenario}`, (t) => {
    let frame;
    let timer;
    let calls = 0;
    const cancelled = [];
    t.mock.method(globalThis, 'setTimeout', (callback) => { timer = callback; return 7; });
    t.mock.method(globalThis, 'clearTimeout', (id) => cancelled.push(`timer:${id}`));
    const oldFrame = globalThis.requestAnimationFrame;
    const oldCancel = globalThis.cancelAnimationFrame;
    globalThis.requestAnimationFrame = (callback) => { frame = callback; return 8; };
    globalThis.cancelAnimationFrame = (id) => cancelled.push(`frame:${id}`);
    t.after(() => {
      if (oldFrame === undefined) delete globalThis.requestAnimationFrame;
      else globalThis.requestAnimationFrame = oldFrame;
      if (oldCancel === undefined) delete globalThis.cancelAnimationFrame;
      else globalThis.cancelAnimationFrame = oldCancel;
    });
    const cancel = scheduleAgentSocketEventFlush(() => calls++);
    assert.equal(typeof timer, 'function', 'event delivery needs a timer even when animation frames exist');
    if (scenario === 'unmount') cancel();
    if (scenario === 'frame wins') frame();
    timer();
    frame();
    assert.equal(calls, scenario === 'unmount' ? 0 : 1);
    assert.ok(cancelled.includes('timer:7'));
    assert.ok(cancelled.includes('frame:8'));
  });
}
