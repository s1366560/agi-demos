import { defineContentScript } from 'wxt/utils/define-content-script';
import type { DomNodeLike } from '../src/monitor';
import { scanAndNeutralize } from '../src/monitor';

const LOADED_MARKER = '__memstackForeignFrameMonitorLoaded';

/**
 * Foreign-frame monitor (design §2.6 isolation): neutralizes iframes that
 * embed OTHER extensions' chrome-extension:// pages inside tabs leased to
 * the agent. Injected programmatically by the service worker into leased
 * tabs (all frames), never manifest-registered.
 */
export default defineContentScript({
  matches: ['<all_urls>'],
  registration: 'runtime',
  runAt: 'document_start',
  allFrames: true,
  main() {
    const marker = window as unknown as Record<string, boolean>;
    if (marker[LOADED_MARKER]) return;
    marker[LOADED_MARKER] = true;

    const ownExtensionId = chrome.runtime.id;

    // Prefer chrome.dom.openOrClosedShadowRoot so closed shadow roots are
    // walked too; fall back to the open-shadow-root property.
    const resolveShadowRoot = (node: DomNodeLike): DomNodeLike | null => {
      try {
        const dom = (chrome as unknown as { dom?: { openOrClosedShadowRoot?: (el: Element) => ShadowRoot | null } }).dom;
        if (dom?.openOrClosedShadowRoot) {
          const root = dom.openOrClosedShadowRoot(node as unknown as Element);
          if (root) return root as unknown as DomNodeLike;
        }
      } catch {
        /* not a shadow host */
      }
      return node.shadowRoot ?? null;
    };

    const scan = (root: DomNodeLike) => scanAndNeutralize(root, ownExtensionId, resolveShadowRoot);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'attributes') {
          scan(mutation.target as unknown as DomNodeLike);
          continue;
        }
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) scan(node as unknown as DomNodeLike);
        }
      }
    });

    const start = () => {
      scan(document as unknown as DomNodeLike);
      observer.observe(document, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['src', 'srcdoc'],
      });
    };

    // document_start: the document exists but documentElement may not yet.
    if (document.documentElement) {
      start();
    } else {
      document.addEventListener('DOMContentLoaded', start, { once: true });
    }
  },
});
