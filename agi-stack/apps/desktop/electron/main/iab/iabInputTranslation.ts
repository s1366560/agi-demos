/**
 * Codex-iab style input translation.
 *
 * `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` / `Input.insertText`
 * are NOT sent over the debugger: trusted CDP input would move the user's
 * real focus and pointer state. Instead the iab backend translates them into
 * in-page synthesized events evaluated via `webContents.executeJavaScript`
 * (elementFromPoint hit-test → PointerEvent/MouseEvent sequence, focus
 * management on the hit element), so agent input never steals the user's
 * real focus. All other CDP methods pass through the debugger untouched.
 *
 * Cross-origin iframes are unsupported: the hit-test and dispatch happen in
 * the top document, so coordinates inside a cross-origin iframe land on the
 * iframe element itself.
 *
 * Pure module: it only builds the page-side script strings, so the
 * translation is unit-testable without Electron.
 */

export const IAB_SYNTHESIZED_INPUT_METHODS = Object.freeze([
  'Input.dispatchMouseEvent',
  'Input.dispatchKeyEvent',
  'Input.insertText',
] as const);

const SYNTHESIZED = new Set<string>(IAB_SYNTHESIZED_INPUT_METHODS);

/** True when an `executeCdp` call must be translated to in-page events. */
export function isIabSynthesizedInputMethod(method: unknown): boolean {
  return typeof method === 'string' && SYNTHESIZED.has(method);
}

/**
 * Page-side helper prelude shared by every synthesized input script. Provides
 * modifier expansion, hit-testing, focus management, and the pointer/mouse
 * dispatch sequence. Injected as the first statement of the IIFE.
 */
const PAGE_HELPERS = String.raw`
const eventTargetForPoint = (x, y) => {
  const hit = document.elementFromPoint(x, y);
  return hit || document.documentElement || document.body;
};
const expandModifiers = (mask) => ({
  altKey: (mask & 1) !== 0,
  ctrlKey: (mask & 2) !== 0,
  metaKey: (mask & 4) !== 0,
  shiftKey: (mask & 8) !== 0,
});
const mouseButtonCode = (name) =>
  name === 'right' ? 2 : name === 'middle' ? 1 : 0;
const mouseButtonsMask = (name) =>
  name === 'right' ? 2 : name === 'middle' ? 4 : name === 'left' ? 1 : 0;
const focusForPress = (target) => {
  const focusable = target && target.closest
    ? target.closest('a,button,input,textarea,select,summary,[tabindex],[contenteditable]')
    : null;
  if (
    focusable &&
    typeof focusable.focus === 'function' &&
    focusable !== document.activeElement &&
    !focusable.disabled
  ) {
    focusable.focus({ preventScroll: true });
  }
};
const dispatchPointerMouse = (target, type, init) => {
  const pointerType = 'pointer' + type;
  const common = Object.assign(
    {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
    },
    init,
  );
  if (typeof PointerEvent === 'function') {
    target.dispatchEvent(
      new PointerEvent(
        pointerType,
        Object.assign({ pointerId: 1, pointerType: 'mouse', isPrimary: true }, common),
      ),
    );
  }
  target.dispatchEvent(new MouseEvent('mouse' + type, common));
};
const dispatchClick = (target, init) => {
  target.dispatchEvent(
    new MouseEvent(
      'click',
      Object.assign(
        { bubbles: true, cancelable: true, composed: true, view: window },
        init,
      ),
    ),
  );
};
const keyEventTarget = () => document.activeElement || document.body || document.documentElement;
`;

type MouseDispatchParams = {
  type?: unknown;
  x?: unknown;
  y?: unknown;
  button?: unknown;
  clickCount?: unknown;
  modifiers?: unknown;
  deltaX?: unknown;
  deltaY?: unknown;
};

function numberOr(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function stringOr(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback;
}

function buildMouseScript(params: MouseDispatchParams): string {
  const type = stringOr(params.type, '');
  if (!['mouseMoved', 'mousePressed', 'mouseReleased', 'mouseWheel'].includes(type)) {
    // Unknown mouse event type: evaluate to false instead of throwing.
    return wrapPageScript('return false;');
  }
  const payload = JSON.stringify({
    x: numberOr(params.x, 0),
    y: numberOr(params.y, 0),
    button: stringOr(params.button, 'none'),
    clickCount: numberOr(params.clickCount, 0),
    modifiers: numberOr(params.modifiers, 0),
    deltaX: numberOr(params.deltaX, 0),
    deltaY: numberOr(params.deltaY, 0),
  });
  const body = String.raw`
const p = ${payload};
const target = eventTargetForPoint(p.x, p.y);
const base = Object.assign(
  {
    clientX: p.x,
    clientY: p.y,
    screenX: p.x,
    screenY: p.y,
    button: mouseButtonCode(p.button),
    buttons: mouseButtonsMask(p.button),
    detail: p.clickCount,
  },
  expandModifiers(p.modifiers),
);
if (p.type === 'mouseWheel') {
  target.dispatchEvent(
    new WheelEvent(
      'wheel',
      Object.assign(
        {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window,
          deltaX: p.deltaX,
          deltaY: p.deltaY,
          deltaMode: 0,
        },
        expandModifiers(p.modifiers),
      ),
    ),
  );
  return true;
}
if (p.type === 'mouseMoved') {
  dispatchPointerMouse(target, 'move', Object.assign(base, { button: 0, buttons: 0, detail: 0 }));
  return true;
}
if (p.type === 'mousePressed') {
  focusForPress(target);
  dispatchPointerMouse(target, 'down', base);
  return true;
}
if (p.type === 'mouseReleased') {
  dispatchPointerMouse(target, 'up', base);
  if (p.button !== 'none' && p.clickCount > 0) {
    dispatchClick(target, base);
  }
  return true;
}
return false;
`;
  return wrapPageScript(body);
}

type KeyDispatchParams = {
  type?: unknown;
  key?: unknown;
  code?: unknown;
  text?: unknown;
  keyIdentifier?: unknown;
  windowsVirtualKeyCode?: unknown;
  modifiers?: unknown;
};

function buildKeyScript(params: KeyDispatchParams): string {
  const type = stringOr(params.type, '');
  const domType =
    type === 'keyDown' || type === 'rawKeyDown'
      ? 'keydown'
      : type === 'keyUp'
        ? 'keyup'
        : type === 'char'
          ? 'keypress'
          : null;
  if (domType === null) {
    return wrapPageScript('return false;');
  }
  const payload = JSON.stringify({
    domType,
    key: stringOr(params.key, ''),
    code: stringOr(params.code, ''),
    text: stringOr(params.text, ''),
    keyCode: numberOr(params.windowsVirtualKeyCode, 0),
    modifiers: numberOr(params.modifiers, 0),
  });
  const body = String.raw`
const p = ${payload};
const target = keyEventTarget();
target.dispatchEvent(
  new KeyboardEvent(
    p.domType,
    Object.assign(
      {
        bubbles: true,
        cancelable: true,
        composed: true,
        view: window,
        key: p.key,
        code: p.code,
        keyCode: p.keyCode,
        which: p.keyCode,
      },
      expandModifiers(p.modifiers),
    ),
  ),
);
return true;
`;
  return wrapPageScript(body);
}

function buildInsertTextScript(params: { text?: unknown }): string {
  const payload = JSON.stringify({ text: stringOr(params.text, '') });
  const body = String.raw`
const p = ${payload};
const target = keyEventTarget();
if (
  typeof document.execCommand === 'function' &&
  document.execCommand('insertText', false, p.text)
) {
  return true;
}
if (
  target &&
  (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)
) {
  const start = target.selectionStart ?? target.value.length;
  const end = target.selectionEnd ?? target.value.length;
  target.value = target.value.slice(0, start) + p.text + target.value.slice(end);
  const caret = start + p.text.length;
  target.setSelectionRange(caret, caret);
  target.dispatchEvent(new InputEvent('input', { bubbles: true, data: p.text, inputType: 'insertText' }));
  return true;
}
return false;
`;
  return wrapPageScript(body);
}

function wrapPageScript(body: string): string {
  return `(() => {${PAGE_HELPERS}${body}})()`;
}

/**
 * Build the page-side script for one CDP Input call, or null when the method
 * is not a synthesized input method (caller passes those to the debugger).
 */
export function buildIabInputScript(method: unknown, params: unknown): string | null {
  if (!isIabSynthesizedInputMethod(method)) return null;
  const record =
    params !== null && typeof params === 'object' && !Array.isArray(params)
      ? (params as Record<string, unknown>)
      : {};
  if (method === 'Input.dispatchMouseEvent') return buildMouseScript(record);
  if (method === 'Input.dispatchKeyEvent') return buildKeyScript(record);
  return buildInsertTextScript(record);
}
