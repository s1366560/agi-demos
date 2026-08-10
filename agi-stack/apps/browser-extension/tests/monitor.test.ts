import { describe, expect, it, vi } from 'vitest';
import {
  MONITOR_CONTENT_SCRIPT_FILE,
  createMonitorInjector,
  isForeignExtensionFrameUrl,
  parseExtensionId,
  scanAndNeutralize,
  type DomNodeLike,
} from '../src/monitor';
import { createChromeMock, flush } from './chrome-mock';

const OWN_ID = 'enbljdpbhdllbbkcjhccmbgpkfmcdkkl';
const FOREIGN_ID = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

function frame(src: string, extra: Record<string, unknown> = {}): DomNodeLike {
  return { tagName: 'IFRAME', src, srcdoc: '<p>payload</p>', children: [], ...extra };
}

describe('extension URL parsing', () => {
  it('parses chrome-extension ids', () => {
    expect(parseExtensionId(`chrome-extension://${FOREIGN_ID}/page.html`)).toBe(FOREIGN_ID);
    expect(parseExtensionId(`chrome-extension://${FOREIGN_ID}`)).toBe(FOREIGN_ID);
  });

  it('returns null for non-extension URLs', () => {
    expect(parseExtensionId('https://example.com')).toBeNull();
    expect(parseExtensionId('about:blank')).toBeNull();
    expect(parseExtensionId('chrome-extension://')).toBeNull();
  });

  it('flags only foreign-extension frames', () => {
    expect(isForeignExtensionFrameUrl(`chrome-extension://${FOREIGN_ID}/x.html`, OWN_ID)).toBe(true);
    expect(isForeignExtensionFrameUrl(`chrome-extension://${OWN_ID}/x.html`, OWN_ID)).toBe(false);
    expect(isForeignExtensionFrameUrl('https://example.com', OWN_ID)).toBe(false);
  });
});

describe('scanAndNeutralize', () => {
  it('neutralizes foreign-extension iframes anywhere in the tree', () => {
    const foreign = frame(`chrome-extension://${FOREIGN_ID}/panel.html`);
    const tree: DomNodeLike = {
      tagName: 'HTML',
      children: [{ tagName: 'BODY', children: [{ tagName: 'DIV', children: [foreign] }] }],
    };
    expect(scanAndNeutralize(tree, OWN_ID)).toBe(1);
    expect(foreign.src).toBe('about:blank');
    expect(foreign.srcdoc).toBeNull();
  });

  it('walks closed shadow roots via the resolver', () => {
    const foreign = frame(`chrome-extension://${FOREIGN_ID}/widget.html`);
    const closedRoot: DomNodeLike = { children: [foreign] };
    const host: DomNodeLike = { tagName: 'DIV', children: [] }; // shadowRoot hidden (closed)
    const tree: DomNodeLike = { tagName: 'HTML', children: [host] };
    const resolveShadowRoot = (node: DomNodeLike) => (node === host ? closedRoot : null);
    expect(scanAndNeutralize(tree, OWN_ID, resolveShadowRoot)).toBe(1);
    expect(foreign.src).toBe('about:blank');
  });

  it('walks open shadow roots without a resolver', () => {
    const foreign = frame(`chrome-extension://${FOREIGN_ID}/widget.html`);
    const host: DomNodeLike = { tagName: 'DIV', children: [], shadowRoot: { children: [foreign] } };
    expect(scanAndNeutralize({ tagName: 'HTML', children: [host] }, OWN_ID)).toBe(1);
    expect(foreign.src).toBe('about:blank');
  });

  it('ignores same-extension, web, and frame-less content', () => {
    const sameExt = frame(`chrome-extension://${OWN_ID}/options/index.html`);
    const web = frame('https://example.com/embed');
    const noSrc = frame('');
    const div: DomNodeLike = { tagName: 'DIV', children: [] };
    const tree: DomNodeLike = {
      tagName: 'HTML',
      children: [sameExt, web, noSrc, div],
    };
    expect(scanAndNeutralize(tree, OWN_ID)).toBe(0);
    expect(sameExt.src).toBe(`chrome-extension://${OWN_ID}/options/index.html`);
    expect(web.src).toBe('https://example.com/embed');
  });

  it('also matches FRAME elements', () => {
    const legacy = frame(`chrome-extension://${FOREIGN_ID}/old.html`, { tagName: 'FRAME' });
    expect(scanAndNeutralize({ children: [legacy] }, OWN_ID)).toBe(1);
    expect(legacy.src).toBe('about:blank');
  });

  it('uses setAttribute/removeAttribute when available (real DOM path)', () => {
    const setAttribute = vi.fn();
    const removeAttribute = vi.fn();
    const getAttribute = vi.fn(() => `chrome-extension://${FOREIGN_ID}/page.html`);
    const domLike = {
      tagName: 'IFRAME',
      getAttribute,
      setAttribute,
      removeAttribute,
      children: [],
    };
    expect(scanAndNeutralize({ children: [domLike] }, OWN_ID)).toBe(1);
    expect(setAttribute).toHaveBeenCalledWith('src', 'about:blank');
    expect(removeAttribute).toHaveBeenCalledWith('srcdoc');
  });
});

describe('monitor injector', () => {
  it('injects the monitor into all frames once per tab', async () => {
    const { chrome } = createChromeMock();
    const injector = createMonitorInjector(chrome);
    injector.ensureMonitorInjected(7);
    injector.ensureMonitorInjected(7);
    await flush();
    expect(chrome.scripting.executeScript).toHaveBeenCalledTimes(1);
    expect(chrome.scripting.executeScript).toHaveBeenCalledWith({
      target: { tabId: 7, allFrames: true },
      files: [MONITOR_CONTENT_SCRIPT_FILE],
    });
  });

  it('allows a retry when the injection fails', async () => {
    const { chrome } = createChromeMock();
    chrome.scripting.executeScript.mockRejectedValueOnce(new Error('tab gone'));
    const injector = createMonitorInjector(chrome);
    injector.ensureMonitorInjected(7);
    await flush();
    injector.ensureMonitorInjected(7);
    await flush();
    expect(chrome.scripting.executeScript).toHaveBeenCalledTimes(2);
  });
});
