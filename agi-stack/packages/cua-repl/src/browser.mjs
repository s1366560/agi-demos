import { duration, imageBytes, index, point, selectionCursor, serializable, stringValue, target, unwrap } from './values.mjs';
import { browserAuthSelector, playwright } from './locators.mjs';

const browserCapabilities = { visibility: ['get', 'set'], viewport: ['set', 'reset'], management: ['getAuditTrail'] };
const managementMethods = { tabs: ['get', 'query', 'update', 'move', 'group', 'ungroup', 'remove'], windows: ['get', 'getAll', 'create', 'update'], tabGroups: ['get', 'query', 'update', 'move'], bookmarks: ['get', 'getChildren', 'getTree', 'getSubTree', 'search', 'create', 'update', 'move', 'remove', 'removeTree'] };
const tabCapabilities = { cdp: ['send', 'readEvents'], webmcp: ['listTools', 'callTool'], browserAuth: ['request'], pageAssets: ['list', 'bundle'], botDetection: ['check'] };
const browserFamily = info => info.family ?? info.type ?? info.id;
const browserType = info => info.type ?? browserFamily(info);
const normalizedUrl = url => {
  if (typeof url !== 'string' || !url.trim()) throw new TypeError('URL must be a non-empty string');
  const result = URL.canParse(url) ? url : `https://${url}`;
  if (!URL.canParse(result)) throw new TypeError('invalid URL');
  return result;
};

function tabMention(value) {
  const url = new URL(value);
  const legacy = url.hostname === 'browser' && !url.username;
  const packaged = url.hostname === 'openai-bundled' && ['browser', 'chrome', 'chrome-dev', 'chrome-internal'].includes(url.username);
  if (url.protocol !== 'plugin:' || (!legacy && !packaged) || url.password || !['', '/'].includes(url.pathname) || url.hash) throw new Error('invalid tab mention');
  const fields = Object.fromEntries(url.searchParams);
  if (url.searchParams.size !== Object.keys(fields).length) throw new Error('duplicate tab mention fields');
  if (fields.mention !== 'tab-v1' || !['browserId', 'tabId', 'title', 'url'].every(key => Object.hasOwn(fields, key)) || !fields.browserId.trim() || !fields.tabId.trim()) throw new Error('incomplete tab mention');
  const source = legacy || url.username === 'browser' ? fields.source ?? 'iab' : 'extension';
  if (!['iab', 'extension'].includes(source)) throw new Error('invalid tab mention source');
  return { ...fields, source };
}

function capabilities(call, definitions, document) {
  return Object.freeze({ list: () => call('capabilities.list', []), get: async name => {
    if (!Object.hasOwn(definitions, name)) throw new Error(`unknown capability ${JSON.stringify(name)}`);
    const advertised = await call('capabilities.list', []);
    if (!(advertised ?? []).some(entry => (typeof entry === 'string' ? entry : entry.id ?? entry.name) === name)) throw new Error(`capability ${name} is unavailable on this provider`);
    const handle = Object.fromEntries(definitions[name].map(method => [method, (...args) => call(`capability.${name}.${method}`, serializable(args))]));
    handle.documentation = () => document(`capability:${name}`, true);
    if (name === 'management') for (const [namespace, methods] of Object.entries(managementMethods)) handle[namespace] = Object.freeze(Object.fromEntries(methods.map(method => [method, (...args) => call(`capability.management.${namespace}.${method}`, serializable(args))])));
    if (name === 'browserAuth') handle.request = options => {
      const withSelector = entry => ({ ...entry, ...(entry.selector === undefined ? {} : { selector: browserAuthSelector(entry.selector) }) });
      return call('capability.browserAuth.request', serializable([{ ...options,
        fields: options.fields.map(withSelector), ...(options.options ? { options: options.options.map(withSelector) } : {}),
        ...(options.submit ? { submit: withSelector(options.submit) } : {}),
      }]));
    };
    return Object.freeze(handle);
  } });
}

export function browserSurface({ rpc, write, emitImage, platform, document }) {
  const atomic = async (tool, args = {}) => unwrap(await rpc('browser.call', { tool, arguments: args }));
  // RPC already decodes result values and rejects transport errors. Page strings
  // and objects (including an `error` property) must remain application data.
  const operation = (browserId, tabId, operation, args = []) => rpc('browser.operation', { browserId, ...(tabId === undefined ? {} : { tabId }), operation, args });
  const listBrowsers = async ({ emit = true } = {}) => {
    const result = await operation(undefined, undefined, 'browsers.list');
    const browsers = result.browsers ?? result;
    if (emit) write(browsers);
    return browsers;
  };
  const listTabs = async ({ browser, emit = true } = {}) => {
    const browsers = browser ? [await resolveBrowser({ id: browser })] : await listBrowsers({ emit: false });
    const tabs = (await Promise.all(browsers.map(async info => {
      const result = await operation(info.id, undefined, 'tabs.list');
      const managed = result.tabs ?? result;
      const user = browserFamily(info) === 'dot' || info.userTabs === true
        ? await operation(info.id, undefined, 'user.openTabs') : [];
      return [...new Map([...(user.tabs ?? user), ...managed].map(tab => [String(tab.id ?? tab.tabId), tab])).values()]
        .map(tab => ({ ...tab, id: String(tab.id ?? tab.tabId), browserId: info.id }));
    }))).flat();
    if (emit) write(tabs);
    return tabs;
  };
  const resolveBrowser = async (options = {}) => {
    if (options.id !== undefined && options.extensionInstanceId !== undefined) throw new Error('Specify either id or extensionInstanceId, not both');
    if (options.id === undefined && options.extensionInstanceId === undefined) {
      const selected = await operation(undefined, undefined, 'browsers.resolve', [{ ...(options.url === undefined ? {} : { url: normalizedUrl(options.url) }) }]);
      if (!selected || typeof selected.id !== 'string' || !selected.id) throw new Error('host did not resolve a browser identity');
      return selected;
    }
    const browsers = await listBrowsers({ emit: false });
    let matches = browsers;
    if (options.id) matches = matches.filter(b => b.id === options.id || b.metadata?.stableId === options.id || browserFamily(b) === options.id || b.backend === options.id);
    if (options.extensionInstanceId) matches = matches.filter(b => b.metadata?.extensionInstanceId === options.extensionInstanceId);
    if (matches.length !== 1) throw new Error(matches.length ? 'browser reference is ambiguous' : 'browser is unavailable');
    return matches[0];
  };
  const bindTab = async (info, tab) => {
    const id = String(tab.id ?? tab.tabId);
    const browserId = info.id;
    const call = (name, args) => operation(browserId, id, name, args);
    const native = browserType(info) !== 'mcpapps';
    const nativeCall = (name, args) => {
      if (!native) throw new Error('native input is unavailable for this DOM-only surface; use playwright locators');
      return call(name, args);
    };
    await call('tab.claim', []);
    const observe = async (options = {}, withImage = false) => {
      const result = await call(native ? 'ax.get' : 'playwright.domSnapshot', [{ disableDiffing: options.disableDiffing ?? false }]);
      const state = typeof result === 'string' ? result : result.text ?? result.state ?? result.snapshot;
      if (options.emit !== false) write(state);
      let screenshot;
      if (withImage) {
        const media = await call('tab.screenshot', []);
        screenshot = imageBytes(media);
        if (options.emit !== false) emitImage({ bytes: screenshot, mimeType: media.mimeType });
      }
      return { state, ...(screenshot ? { screenshot } : {}) };
    };
    const handle = { id, playwright: playwright(call), capabilities: capabilities(call, tabCapabilities, document),
      getAXState: async options => (await observe(options)).state,
      getAXStateAndScreenshot: options => observe(options, true),
      getScreenshot: async (options = {}) => {
        const media = await call('tab.screenshot', []);
        const bytes = imageBytes(media);
        if (options.emit !== false) emitImage({ bytes, mimeType: media.mimeType });
        return bytes;
      },
      click: (value, options = {}) => nativeCall('ax.click', [{ ...target(value), mouseButton: options.mouseButton ?? 'left', clickCount: options.clickCount ?? 1, key: options.key, ...duration(options.durationMs, platform) }]),
      drag: (from, to) => nativeCall('ax.drag', [point(from), point(to)]),
      scroll: (value, direction, pages = 1) => nativeCall('ax.scroll', [{ ...target(value), direction, pages }]),
      selectText: (elementIndex, text, options = {}) => nativeCall('ax.selectText', [index(elementIndex), text, { ...options, selectionType: selectionCursor(options.selectionType) }]),
      setValue: (elementIndex, value) => nativeCall('ax.setValue', [index(elementIndex), stringValue(value)]),
      performSecondaryAction: (elementIndex, name) => nativeCall('ax.performSecondaryAction', [index(elementIndex), name]),
      paste: (elementIndex, text, options = {}) => nativeCall('ax.paste', [index(elementIndex, true), text, options]),
      pressKey: (elementIndex, key, options = {}) => nativeCall('ax.pressKey', [index(elementIndex, true), key, duration(options.durationMs, platform)]),
      typeText: (elementIndex, text) => nativeCall('ax.typeText', [index(elementIndex, true), text]),
    };
    for (const name of ['back', 'close', 'forward', 'goto', 'markDeliverable', 'markHandoff', 'reload', 'requestManualHandoff', 'requestUserTakeover', 'title', 'url']) handle[name] = (...args) => call(`tab.${name}`, serializable(args));
    handle.screenshot = async (...args) => imageBytes(await call('tab.screenshot', serializable(args)));
    handle.getJsDialog = async () => {
      const dialog = await call('tab.getJsDialog', []);
      if (!dialog) return null;
      return Object.freeze({ type: dialog.type, accept: text => call('dialog.accept', [dialog.id, text]), dismiss: () => call('dialog.dismiss', [dialog.id]) });
    };
    const surfaces = { ax: ['click', 'drag', 'get', 'paste', 'performSecondaryAction', 'pressKey', 'scroll', 'selectText', 'setValue', 'typeText', 'write'],
      cua: ['click', 'double_click', 'downloadMedia', 'drag', 'keypress', 'move', 'scroll', 'type'],
      dom_cua: ['click', 'double_click', 'downloadMedia', 'get_visible_dom', 'keypress', 'scroll', 'type'],
      content: ['export', 'exportGsuite', 'exportYouTubeTranscript'], clipboard: ['read', 'readText', 'write', 'writeText'], dev: ['logs'] };
    for (const [surface, methods] of Object.entries(surfaces)) handle[surface] = Object.freeze(Object.fromEntries(methods.map(name => [name,
      (...args) => (surface === 'ax' || surface === 'cua' ? nativeCall : call)(`${surface}.${name}`, serializable(args))])));
    handle.ax = Object.freeze({
      ...Object.fromEntries(['drag', 'paste', 'performSecondaryAction', 'scroll', 'selectText', 'setValue', 'typeText'].map(name => [name, handle[name]])),
      click: (value, options = {}) => handle.click(value, { ...options, durationMs: options.duration === undefined ? undefined : Math.round(options.duration * 1000) }),
      pressKey: (elementIndex, key, options = {}) => handle.pressKey(elementIndex, key, { durationMs: options.duration === undefined ? undefined : options.duration * 1000 }),
      get: async (mode = 'state', options = {}) => {
        if (!['state', 'screenshot', 'both'].includes(mode)) throw new Error('unsupported AX observation mode');
        if (!native) return nativeCall('ax.get', []);
        if (mode === 'screenshot') return handle.getScreenshot({ emit: false });
        const state = await observe({ ...options, emit: false }, mode === 'both');
        return mode === 'both' ? state : state.state;
      },
      write: async (mode = 'state', options = {}) => {
        if (!['state', 'screenshot', 'both'].includes(mode)) throw new Error('unsupported AX observation mode');
        if (!native) return nativeCall('ax.write', []);
        if (mode === 'screenshot') await handle.getScreenshot();
        else await observe({ ...options, emit: true }, mode === 'both');
      },
    });
    await document(`browser:${info.id}`);
    await observe({ disableDiffing: true });
    return Object.freeze(handle);
  };
  const getTab = async (reference, options = {}) => {
    if (options.browser !== undefined && (typeof options.browser !== 'string' || !options.browser.trim())) {
      throw new TypeError('getTab browser must be a browser ID string; use browser.browserId');
    }
    let expected;
    if (typeof reference === 'object' && reference?.mention) {
      expected = tabMention(reference.mention);
      const browsers = await listBrowsers({ emit: false });
      const matches = browsers.filter(b => (expected.source === 'extension' ? browserType(b) === 'extension' || ['chrome', 'edge'].includes(browserFamily(b)) : browserType(b) === 'iab')
        && (b.id === expected.browserId || b.metadata?.codexSessionId === expected.browserId || b.metadata?.extensionInstanceId === expected.browserId));
      if (matches.length !== 1) throw new Error('mentioned browser is missing or ambiguous');
      if (options.browser !== undefined && (await resolveBrowser({ id: options.browser })).id !== matches[0].id) throw new Error('requested browser does not match the tab mention browser/profile');
      options = { browser: matches[0].id };
    }
    if (typeof reference === 'object' && reference?.url && !options.browser) throw new Error('URL tab references require an explicit browser');
    if (typeof reference === 'object' && reference?.url && !URL.canParse(reference.url)) throw new Error('URL tab references require an absolute URL');
    if (options.browser === undefined) options = { browser: (await resolveBrowser()).id };
    const tabs = await listTabs({ browser: options.browser, emit: false });
    const matches = tabs.filter(tab => expected ? String(tab.providerTabId ?? tab.id) === expected.tabId && tab.title === expected.title && tab.url === expected.url
      : typeof reference === 'object' ? tab.url === reference.url : tab.id === String(reference) || String(tab.providerTabId) === String(reference));
    if (matches.length !== 1) throw new Error(matches.length ? 'tab reference is ambiguous' : 'tab is unavailable or has changed');
    return bindTab(await resolveBrowser({ id: matches[0].browserId }), matches[0]);
  };
  const createBrowserTab = async (browserId, url = 'about:blank', options = {}) => {
    if (typeof browserId !== 'string' || !browserId.trim()) throw new TypeError('createBrowserTab requires a browser ID');
    if (!options || typeof options !== 'object' || Array.isArray(options)) throw new TypeError('tab options must be an object');
    for (const key of Object.keys(options)) if (!['visible', 'sessionName'].includes(key)) throw new TypeError(`unknown tab option ${key}`);
    if (options.visible !== undefined && typeof options.visible !== 'boolean') throw new TypeError('visible must be a boolean');
    if (options.sessionName !== undefined && typeof options.sessionName !== 'string') throw new TypeError('sessionName must be a string');
    const destination = normalizedUrl(url);
    const info = await resolveBrowser({ id: browserId });
    if (browserType(info) === 'mcpapps') throw new Error('MCP Apps are created by their tools; this provider cannot create tabs');
    const call = (name, args) => operation(info.id, undefined, name, args);
    const visibility = options.visible === undefined ? undefined : await capabilities(call, browserCapabilities, document).get('visibility');
    if (options.sessionName !== undefined) await call('nameSession', [options.sessionName]);
    if (visibility) await visibility.set(options.visible);
    const tab = await call('tabs.new', [destination]);
    return bindTab(info, tab);
  };
  const getBrowser = async (options = {}) => {
    const info = await resolveBrowser(typeof options === 'string' ? { id: options } : options);
    const browserId = info.id;
    const family = browserFamily(info);
    await document(`browser:${browserId}`);
    const call = (name, args) => operation(browserId, undefined, name, args);
    return Object.freeze({ browserId, capabilities: capabilities(call, browserCapabilities, document),
      tabs: Object.freeze({ list: async () => {
        const result = await call('tabs.list', []);
        return (result.tabs ?? result).map(tab => ({ ...tab, id: String(tab.id ?? tab.tabId), browserId }));
      }, get: id => getTab(String(id), { browser: browserId }), new: (url, opts) => createBrowserTab(browserId, url, opts),
        selected: async () => { const tab = await call('tabs.selected', []); return tab ? bindTab(info, tab) : null; } }),
      ...(['chrome', 'edge', 'dot'].includes(family) || info.userTabs === true ? {
        user: Object.freeze({ claimTab: tab => getTab(typeof tab === 'object' ? tab.id ?? tab.tabId : String(tab), { browser: browserId }), openTabs: async () => {
          const result = await call(['iab', 'dot'].includes(family) ? 'user.openTabs' : 'tabs.list', []);
          return (result.tabs ?? result).map(tab => ({ ...tab, id: String(tab.id ?? tab.tabId), browserId }));
        } }),
      } : {}),
      ...(['chrome', 'edge'].includes(family) ? {
        history: options => call('history', serializable([options ?? {}])),
      } : {}),
      documentation: () => document(`browser:${browserId}`, true), ...(family === 'mcpapps' ? {} : { nameSession: name => call('nameSession', [name]) }) });
  };
  return { listBrowsers, listTabs, getBrowser, getTab, createBrowserTab,
    browsers: Object.freeze({ list: () => listBrowsers({ emit: false }), get: id => getBrowser({ id }), getForUrl: url => getBrowser({ url }), getDefault: () => getBrowser() }) };
}
