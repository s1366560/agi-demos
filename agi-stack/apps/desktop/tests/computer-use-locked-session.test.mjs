import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const root = process.env.AGISTACK_DESKTOP_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
const React = require('react');
const jsx = require('react/jsx-runtime');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require(`${root}/src/i18n.js`);
const device = require(`${root}/src/features/settings/ComputerUseDeviceProvider.js`);

const binding = { session_id: 'native-current', run_id: 'run-current', generation: 'lease-current' };
const session = {
  session_id: binding.session_id,
  conversation_id: 'conversation-current',
  run_id: binding.run_id,
  stopped: false,
  presentation: { phase: 'idle', can_resume: false },
};
const snapshot = {
  plugin_id: 'memstack-computer-use', device_id: 'device', helper_available: true,
  scope: { tenant_id: 'tenant', project_id: 'project' },
  instance: { installed: true, enabled: true, revision: 1, locked_use: true },
  grants: [], pending: [], sessions: [session],
  locked_use: { installed: true, enabled: true, state: 'active', phase: 'guarded' },
};

function harness(check) {
  const originalDevice = device.useComputerUseDevice;
  const originalJsx = jsx.jsx, originalJsxs = jsx.jsxs;
  const originalWindow = globalThis.window;
  const calls = [], buttons = [];
  let current = snapshot, busy = false;
  const intercept = delegate => (type, props, ...rest) => {
    if (type === 'button') buttons.push(props);
    return delegate(type, props, ...rest);
  };
  try {
    jsx.jsx = intercept(originalJsx); jsx.jsxs = intercept(originalJsxs);
    device.useComputerUseDevice = () => ({ snapshot: current, busy, stopping: false,
      error: null, client: null, inputStore: null,
      manage: operation => { calls.push(operation); return Promise.resolve(); } });
    check({ calls, buttons,
      setSnapshot: value => { current = value; },
      setLocked: locked_use => { current = { ...snapshot, sessions: [{ ...session, locked_use }] }; },
      setBusy: value => { busy = value; },
      render: (locale = 'en', conversationId = session.conversation_id, runId = session.run_id) => {
        globalThis.window = { localStorage: { getItem: () => locale } };
        buttons.length = 0;
        return renderToStaticMarkup(React.createElement(I18nProvider, null,
          React.createElement(device.ComputerUseActivity, { conversationId, runId })));
      },
    });
  } finally {
    device.useComputerUseDevice = originalDevice;
    jsx.jsx = originalJsx; jsx.jsxs = originalJsxs;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
}

test('session card shows its armed phase while ordinary computer use is idle and keeps Stop usable', () => {
  harness(h => {
    h.setLocked({ ...binding, enabled: true, state: 'active', phase: 'armed' });
    h.setBusy(true);
    const html = h.render();
    assert.match(html, /Waiting for the screen to lock/);
    assert.match(html, /Lock the Mac to continue/);
    assert.match(html, /role="status"/);
    assert.deepEqual(h.calls, [], 'rendering phase never probes or mutates native state');
    const stop = h.buttons.find(button => button.children === 'Stop computer use');
    assert.equal(stop.disabled, false);
    stop.onClick();
    assert.deepEqual(h.calls, [{ action: 'stop', session_id: binding.session_id }]);
    const zh = h.render('zh-CN');
    assert.match(zh, /等待锁屏/);
    assert.match(zh, /请锁定 Mac 以继续/);
    assert.match(zh, /停止电脑操作/);
  });
});

test('fresh bound phases update the card with native stage and localized guidance', () => {
  harness(h => {
    for (const [phase, en, zh] of [
      ['covering', 'Covering the desktop', '正在遮挡桌面'],
      ['unlocking', 'Temporarily unlocking under the cover', '正在遮罩下临时解锁'],
      ['guarded', 'Working under the cover', '正在遮罩下工作'],
      ['relocking', 'Locking the screen again', '正在重新锁屏'],
    ]) {
      h.setLocked(phase === 'relocking'
        ? { revoked_binding: binding, enabled: false, state: 'suppressed', phase,
            requires_manual_unlock: true }
        : { ...binding, enabled: true, state: 'active', phase });
      assert.ok(h.render().includes(en));
      const translated = h.render('zh-CN');
      assert.ok(translated.includes(zh));
      assert.doesNotMatch(translated, /cua\.lockedUse\./);
      assert.doesNotMatch(translated, /请锁定 Mac 以继续/);
    }
    assert.deepEqual(h.calls, []);
  });
});

test('unbound device state, missing generation and another session or run never become this task phase', () => {
  harness(h => {
    for (const locked of [undefined, {}, { ...binding, generation: '' },
      { ...binding, generation: undefined }, { ...binding, session_id: 'native-other' },
      { ...binding, run_id: 'run-other' }]) {
      h.setLocked(locked && { ...locked, state: 'active', phase: 'guarded' });
      assert.doesNotMatch(h.render(), /Working under the cover/);
    }
    h.setSnapshot({ ...snapshot, sessions: [{ ...session,
      conversation_id: 'conversation-other', locked_use: { ...binding, phase: 'armed' } }] });
    assert.equal(h.render(), '');
    h.setLocked({ ...binding, state: 'active', phase: 'armed' });
    assert.equal(h.render('en', session.conversation_id, 'run-other'), '');
  });
});

test('revoked native failure and manual unlock are explicit without claiming guarded success', () => {
  harness(h => {
    h.setLocked({ revoked_binding: binding, state: 'suppressed', phase: 'idle', enabled: false,
      requires_manual_unlock: true, reason: 'guardian_unavailable',
      failure: { stage: 'guardian_renew', reason: 'guard_not_ready' } });
    const html = h.render();
    assert.match(html, /Lock continuity stopped/);
    assert.match(html, /Unlock the Mac yourself/);
    assert.match(html, /role="alert"/);
    assert.match(html, /guardian_unavailable/);
    assert.doesNotMatch(html, /Working under the cover/);
    assert.match(h.render('zh-CN'), /锁屏持续操作已停止/);
  });
});

test('unknown protocol phase is displayed as unknown and never inferred from a reason string', () => {
  harness(h => {
    h.setLocked({ ...binding, state: 'active', phase: 'future_phase', reason: 'guarded' });
    const html = h.render();
    assert.match(html, /Lock continuity status unavailable/);
    assert.doesNotMatch(html, /Working under the cover/);
    h.setLocked(undefined);
    assert.doesNotMatch(h.render(), /Lock continuity status unavailable/);
    assert.deepEqual(h.calls, []);
  });
});

test('contradictory or incomplete active status never claims that this task is armed or guarded', () => {
  harness(h => {
    for (const phase of ['armed', 'covering', 'unlocking', 'guarded']) {
      for (const incomplete of [
        { enabled: false, state: 'active' },
        { state: 'active' },
        { enabled: 'true', state: 'active' },
        { enabled: true, state: 'available' },
        { enabled: true },
      ]) {
        h.setLocked({ ...binding, phase, ...incomplete });
        const html = h.render();
        assert.match(html, /Lock continuity status unavailable/);
        assert.doesNotMatch(html, /Waiting for the screen to lock|Working under the cover/);
      }
    }
    assert.deepEqual(h.calls, []);
  });
});


test('revoked status remains display only and does not require an active lease expiry', () => {
  harness(h => {
    const terminal = { revoked_binding: binding, state: 'suppressed', phase: 'relocking',
      enabled: false, requires_manual_unlock: true };
    h.setLocked(terminal);
    assert.match(h.render(), /Locking the screen again/);
    assert.match(h.render(), /Unlock the Mac yourself/);
    assert.match(h.render('zh-CN'), /请先自行解锁 Mac/);
    assert.deepEqual(h.calls, [], 'displaying revoked status never renews, probes or resumes');
    h.setLocked({ ...terminal, state: 'available', requires_manual_unlock: false });
    assert.match(h.render(), /Locking the screen again/);
    assert.doesNotMatch(h.render(), /Unlock the Mac yourself/);
  });
});

test('terminal display rejects missing, mixed, contradictory and foreign revoked identity', () => {
  harness(h => {
    const terminal = { revoked_binding: binding, state: 'suppressed', phase: 'idle',
      enabled: false, requires_manual_unlock: true };
    const invalid = [
      { ...terminal, revoked_binding: undefined },
      { ...terminal, revoked_binding: {} },
      { ...terminal, revoked_binding: null },
      { ...terminal, revoked_binding: [] },
      { ...terminal, revoked_binding: 'invalid' },
      { ...terminal, revoked_binding: { ...binding, session_id: 'other-session' } },
      { ...terminal, revoked_binding: { ...binding, run_id: 'other-run' } },
      { ...terminal, revoked_binding: { ...binding, generation: '' } },
      { ...terminal, revoked_binding: { ...binding, generation: undefined } },
      { ...terminal, ...binding },
      { ...terminal, session_id: null },
      { ...terminal, enabled: true },
      { ...terminal, enabled: undefined },
      { ...terminal, enabled: 'false' },
      { ...terminal, state: 'active' },
      { ...terminal, state: undefined },
      { ...terminal, phase: 'guarded' },
      { ...terminal, phase: undefined },
      { ...terminal, requires_manual_unlock: undefined },
      { ...terminal, requires_manual_unlock: false },
      { ...terminal, requires_manual_unlock: 'true' },
    ];
    for (const value of invalid) {
      h.setLocked(value);
      assert.doesNotMatch(h.render(), /Lock continuity stopped|Unlock the Mac yourself|Working under the cover/);
    }
    h.setLocked({ ...binding, state: 'suppressed', phase: 'idle', enabled: false,
      requires_manual_unlock: true });
    assert.doesNotMatch(h.render(), /Lock continuity stopped|Unlock the Mac yourself/);
    assert.deepEqual(h.calls, []);
  });
});
