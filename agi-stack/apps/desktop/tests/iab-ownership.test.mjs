import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const module = { exports: {} };
new Function('exports', ts.transpileModule(readFileSync(new URL('../electron/main/iab/iabOwnership.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)(module.exports);
const { IabOwnership, browserCaller } = module.exports;
const root = { sessionId: 'main', mainSessionId: 'main', callerId: 'root', turnId: 'turn1', allowDot: false };
const child = { sessionId: 'child', mainSessionId: 'main', callerId: 'child1', turnId: 'turn1', allowDot: true };
const sibling = { ...child, sessionId: 'sibling', callerId: 'child2' };

test('Dot lists main-session user tabs separately from caller claims and never aliases child IAB', () => {
  const owner = new IabOwnership();
  owner.created(1, root, 'user'); owner.created(2, child, 'agent');
  assert.deepEqual(owner.list(root, 'iab', false), []);
  assert.deepEqual(owner.list(root, 'iab', true), [1]);
  assert.deepEqual(owner.list(child, 'iab', false), [2]);
  assert.deepEqual(owner.list(child, 'dot', true), [1]);
  assert.deepEqual(owner.list(child, 'dot', false), []);
  owner.claim(1, child, 'dot');
  assert.deepEqual(owner.list(child, 'dot', false), [1]);
  assert.throws(() => owner.claim(1, sibling, 'dot'), /claimed/);
  assert.throws(() => owner.claim(2, child, 'dot'), /scope/);
  assert.throws(() => owner.list(root, 'dot', true), /not available/);
});

test('turn cleanup releases exclusive claims, closes temporary tabs, and resets marks on reclaim', () => {
  const owner = new IabOwnership();
  owner.created(1, root, 'user'); owner.created(2, child, 'agent', 'dot');
  owner.claim(1, child, 'dot'); owner.mark(2, child, 'dot', 'handoff');
  assert.deepEqual(owner.finishTurn('turn1'), []);
  const next = { ...sibling, turnId: 'turn2' };
  owner.claim(1, next, 'dot'); owner.claim(2, next, 'dot');
  assert.deepEqual(owner.finishTurn('turn2'), [2]);
  assert.deepEqual(owner.list({ ...root, turnId: 'turn3' }, 'iab', true), [1]);
});

test('user takeover blocks the interrupted caller but permits a later turn', () => {
  const owner = new IabOwnership(); owner.created(1, root, 'user'); owner.claim(1, child, 'dot');
  owner.takeOver(1);
  assert.throws(() => owner.claim(1, child, 'dot'), /user took control/);
  owner.claim(1, { ...child, turnId: 'next' }, 'dot');
  assert.equal(owner.metadata(1).controller, 'agent');
});

test('caller is validated and cannot request Dot without trusted child scope', () => {
  assert.deepEqual(browserCaller({ _browserCaller: root }), root);
  assert.throws(() => browserCaller({}), /scope/);
  assert.throws(() => browserCaller({ _browserCaller: { ...root, turnId: '' } }), /scope/);
});

 test('UI activation alone selects where user tabs belong and popups retain their parent scope', () => {
  const owner = new IabOwnership(); owner.activateSession('selected'); owner.observe(root);
  owner.created(1, null, 'user');
  assert.equal(owner.metadata(1).sessionId, 'selected');
  assert.equal(owner.metadata(1).controller, 'user');
  owner.created(2, child, 'agent', 'dot'); owner.createdFrom(3, 2);
  assert.deepEqual(owner.list(child, 'dot', false), [2, 3]);
  assert.deepEqual(owner.finishTurn('turn1'), [2, 3]);
});
