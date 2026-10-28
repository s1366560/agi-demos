import { imageBytes, serializable } from './values.mjs';

const selectors = ['locator', 'getByRole', 'getByText', 'getByLabel', 'getByPlaceholder', 'getByTestId'];
const actions = ['allTextContents', 'check', 'click', 'count', 'dblclick', 'downloadMedia', 'evaluate', 'evaluateAll', 'fill',
  'getAttribute', 'innerText', 'isEnabled', 'isVisible', 'press', 'pressSequentially', 'selectOption', 'setChecked', 'textContent', 'type', 'uncheck', 'waitFor'];
const chains = new WeakMap();

export function browserAuthSelector(value) {
  if (typeof value === 'string' && value) return { steps: [{ kind: 'locator', args: [value] }] };
  const steps = chains.get(value);
  if (!steps) throw new TypeError('browser auth selectors must be a CSS string or locator');
  return { steps };
}

export function locator(call, steps = [], frame = false) {
  const handle = {};
  const append = (kind, args, isFrame = frame) => locator(call, [...steps, { kind, args: serializable(args) }], isFrame);
  for (const name of selectors) handle[name] = (...args) => append(name, args, false);
  handle.frameLocator = (...args) => append('frameLocator', args, true);
  if (!frame) {
    for (const name of actions) handle[name] = (...args) => call('playwright.locator', [steps, name, serializable(args)]);
    for (const name of ['first', 'last', 'nth', 'filter']) handle[name] = (...args) => {
      if (name === 'filter' && args[0]) args = [{ ...args[0], has: args[0].has ? chains.get(args[0].has) : undefined, hasNot: args[0].hasNot ? chains.get(args[0].hasNot) : undefined }];
      return append(name, args);
    };
    for (const name of ['and', 'or']) handle[name] = other => {
      const otherSteps = chains.get(other);
      if (!otherSteps) throw new TypeError('locator composition requires another locator');
      return append(name, [otherSteps]);
    };
    handle.all = async () => Array.from({ length: await handle.count() }, (_, i) => handle.nth(i));
  }
  chains.set(handle, steps);
  return Object.freeze(handle);
}

export function playwright(call) {
  const handle = { ...locator(call, [], true) };
  for (const name of ['domSnapshot', 'elementInfo', 'evaluate', 'waitForLoadState', 'waitForURL', 'waitForTimeout']) {
    handle[name] = (...args) => call(`playwright.${name}`, serializable(args));
  }
  handle.elementScreenshot = async (...args) => imageBytes(await call('playwright.elementScreenshot', serializable(args)));
  handle.waitForEvent = async (...args) => {
    const result = await call('playwright.waitForEvent', serializable(args));
    if (args[0] === 'download') return Object.freeze({ path: options => call('download.path', [result.id, serializable(options ?? {})]) });
    if (args[0] === 'filechooser') return Object.freeze({ isMultiple: () => Boolean(result.multiple), setFiles: (files, options) => call('filechooser.setFiles', [result.id, files, serializable(options ?? {})]) });
    return result;
  };
  handle.expectNavigation = async (action, options) => {
    const armed = await call('playwright.armNavigation', [options ?? {}]);
    try { const result = await action(); await call('playwright.waitNavigation', [armed.id, options ?? {}]); return result; }
    catch (error) { await call('playwright.cancelNavigation', [armed.id]); throw error; }
  };
  return Object.freeze(handle);
}
