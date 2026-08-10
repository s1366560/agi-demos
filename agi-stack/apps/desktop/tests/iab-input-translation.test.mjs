import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildIabInputScript,
  isIabSynthesizedInputMethod,
} = require('/tmp/agistack-desktop-test-dist/electron/main/iab/iabInputTranslation.js');
const { parseIabCursorConsoleMessage } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/iab/iabCursor.js',
);

test('only the Input.* CDP methods are synthesized in-page', () => {
  assert.equal(isIabSynthesizedInputMethod('Input.dispatchMouseEvent'), true);
  assert.equal(isIabSynthesizedInputMethod('Input.dispatchKeyEvent'), true);
  assert.equal(isIabSynthesizedInputMethod('Input.insertText'), true);
  assert.equal(isIabSynthesizedInputMethod('Page.captureScreenshot'), false);
  assert.equal(isIabSynthesizedInputMethod('Runtime.evaluate'), false);
  assert.equal(isIabSynthesizedInputMethod('Input.synthesizeScrollGesture'), false);
  assert.equal(isIabSynthesizedInputMethod(undefined), false);
});

test('mouse press synthesis hit-tests, manages focus, and keeps modifiers', () => {
  const script = buildIabInputScript('Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x: 12.5,
    y: 40,
    button: 'left',
    clickCount: 1,
    modifiers: 9, // Alt | Shift
  });
  assert.ok(script.includes('elementFromPoint'));
  assert.ok(script.includes('focusForPress'));
  assert.ok(script.includes('PointerEvent'));
  assert.ok(script.includes('"x":12.5'));
  assert.ok(script.includes('"modifiers":9'));
});

test('mouse release synthesis dispatches click for counted releases', () => {
  const script = buildIabInputScript('Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x: 1,
    y: 2,
    button: 'left',
    clickCount: 1,
  });
  assert.ok(script.includes("dispatchClick"));
  assert.ok(script.includes("'up'"));
});

test('wheel, key, and insertText synthesis map to page events', () => {
  const wheel = buildIabInputScript('Input.dispatchMouseEvent', {
    type: 'mouseWheel',
    x: 0,
    y: 0,
    deltaX: 0,
    deltaY: 240,
  });
  assert.ok(wheel.includes('WheelEvent'));
  assert.ok(wheel.includes('"deltaY":240'));

  const key = buildIabInputScript('Input.dispatchKeyEvent', {
    type: 'keyDown',
    key: 'Enter',
    code: 'Enter',
    windowsVirtualKeyCode: 13,
  });
  assert.ok(key.includes('KeyboardEvent'));
  assert.ok(key.includes('"domType":"keydown"'));
  assert.ok(key.includes('"keyCode":13'));

  const insert = buildIabInputScript('Input.insertText', { text: 'hello "world"' });
  assert.ok(insert.includes("execCommand('insertText'"));
  assert.ok(insert.includes('hello \\"world\\"'));
});

test('unknown input shapes evaluate to false instead of throwing page-side', () => {
  const unknownMouse = buildIabInputScript('Input.dispatchMouseEvent', { type: 'mouseDragged' });
  assert.ok(unknownMouse.includes('return false;'));
  const unknownKey = buildIabInputScript('Input.dispatchKeyEvent', { type: 'rawChar' });
  assert.ok(unknownKey.includes('return false;'));
});

test('non-input methods are not translated', () => {
  assert.equal(buildIabInputScript('Page.navigate', { url: 'https://example.com' }), null);
});

test('cursor console bridge parses arrivals and ignores page logs', () => {
  assert.deepEqual(
    parseIabCursorConsoleMessage('__memstack_cursor__:{"type":"AGENT_CURSOR_ARRIVED","moveSequence":3}'),
    { moveSequence: 3 },
  );
  assert.equal(parseIabCursorConsoleMessage('ordinary page log'), null);
  assert.equal(parseIabCursorConsoleMessage('__memstack_cursor__:not json'), null);
  assert.equal(
    parseIabCursorConsoleMessage('__memstack_cursor__:{"type":"AGENT_CURSOR_STATE"}'),
    null,
  );
});
