import type { ChromeApi } from './chrome-api';

export const MONITOR_CONTENT_SCRIPT_FILE = 'content-scripts/foreign-frame-monitor.js';
export const EXTENSION_URL_PREFIX = 'chrome-extension://';

/** Extension id out of a chrome-extension://<id>/... URL, else null. */
export function parseExtensionId(url: string): string | null {
  if (!url.startsWith(EXTENSION_URL_PREFIX)) return null;
  const rest = url.slice(EXTENSION_URL_PREFIX.length);
  const slash = rest.indexOf('/');
  const id = slash === -1 ? rest : rest.slice(0, slash);
  return id.length > 0 ? id : null;
}

/** True when the URL belongs to a *different* extension than `ownExtensionId`. */
export function isForeignExtensionFrameUrl(url: string, ownExtensionId: string): boolean {
  const id = parseExtensionId(url);
  return id !== null && id !== ownExtensionId;
}

/**
 * Minimal structural view of an iframe/frame element — satisfied by both the
 * real DOM and the test fakes.
 */
export interface FrameElementLike {
  tagName?: string;
  src?: string;
  srcdoc?: string | null;
  getAttribute?(name: string): string | null;
  setAttribute?(name: string, value: string): void;
  removeAttribute?(name: string): void;
}

/** Structural DOM node for the shadow-aware walk. */
export interface DomNodeLike {
  tagName?: string;
  children?: ArrayLike<DomNodeLike> | null;
  shadowRoot?: DomNodeLike | null;
}

/** Cut a foreign frame off: blank the src, drop any srcdoc payload. */
export function neutralizeFrame(frame: FrameElementLike): void {
  if (typeof frame.setAttribute === 'function') {
    frame.setAttribute('src', 'about:blank');
    if (typeof frame.removeAttribute === 'function') frame.removeAttribute('srcdoc');
  } else {
    frame.src = 'about:blank';
  }
  if ('srcdoc' in frame) frame.srcdoc = null;
}

function frameSource(frame: FrameElementLike): string {
  if (typeof frame.getAttribute === 'function') {
    return frame.getAttribute('src') ?? frame.src ?? '';
  }
  return frame.src ?? '';
}

export type ShadowRootResolver = (node: DomNodeLike) => DomNodeLike | null;

/**
 * Walk `root` depth-first — including open and (via `resolveShadowRoot`)
 * closed shadow roots — and neutralize every iframe/frame whose src is a
 * chrome-extension:// URL of a different extension. Returns the count.
 */
export function scanAndNeutralize(
  root: DomNodeLike,
  ownExtensionId: string,
  resolveShadowRoot?: ShadowRootResolver,
): number {
  let neutralized = 0;
  const stack: DomNodeLike[] = [root];
  while (stack.length > 0) {
    const node = stack.pop() as DomNodeLike;
    const tag = node.tagName?.toUpperCase();
    if (tag === 'IFRAME' || tag === 'FRAME') {
      const src = frameSource(node as FrameElementLike);
      if (src && isForeignExtensionFrameUrl(src, ownExtensionId)) {
        neutralizeFrame(node as FrameElementLike);
        neutralized++;
      }
    }
    const shadow = resolveShadowRoot?.(node) ?? node.shadowRoot ?? null;
    if (shadow) stack.push(shadow);
    const children = node.children;
    if (children) {
      for (let i = children.length - 1; i >= 0; i--) {
        const child = children[i];
        if (child) stack.push(child);
      }
    }
  }
  return neutralized;
}

/**
 * Service-worker side: inject the monitor content script into every frame
 * of a tab that became leased (assignTab / createTab). Best-effort and
 * idempotent per SW lifetime; the content script also self-guards.
 */
export function createMonitorInjector(chrome: ChromeApi) {
  const injected = new Set<number>();
  return {
    ensureMonitorInjected(tabId: number): void {
      if (injected.has(tabId)) return;
      injected.add(tabId);
      void chrome.scripting
        .executeScript({
          target: { tabId, allFrames: true },
          files: [MONITOR_CONTENT_SCRIPT_FILE],
        })
        .catch(() => {
          injected.delete(tabId); // allow a later retry
        });
    },
  };
}

export type MonitorInjector = ReturnType<typeof createMonitorInjector>;
