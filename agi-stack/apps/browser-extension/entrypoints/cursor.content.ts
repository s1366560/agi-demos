import { defineContentScript } from 'wxt/utils/define-content-script';
import type { CursorState } from '../src/cursor/cursor-manager';
import { CURSOR_MESSAGE_TYPES } from '../src/cursor/cursor-manager';
import { CursorAnimator } from '../src/cursor/engine';
import { createCursorOverlay } from '../src/cursor/overlay';

const LOADED_MARKER = '__memstackAgentCursorLoaded';

/**
 * Virtual cursor content script. Injected on demand by the service worker
 * (see src/cursor/cursor-manager.ts); intentionally NOT manifest-registered.
 * Stateless: the SW holds the last state, this script pulls it on load and
 * on bfcache restore (pageshow).
 */
export default defineContentScript({
  matches: ['<all_urls>'],
  registration: 'runtime',
  runAt: 'document_idle',
  main() {
    // Top frame only; guard against double injection (e.g. SW restart).
    if (window.top !== window.self) return;
    const marker = window as unknown as Record<string, boolean>;
    if (marker[LOADED_MARKER]) return;
    marker[LOADED_MARKER] = true;

    const overlay = createCursorOverlay(document);
    const animator = new CursorAnimator({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener('resize', () => {
      animator.setViewport({ width: window.innerWidth, height: window.innerHeight });
    });

    let lastSequence = 0;
    let rafId: number | null = null;
    let lastTime = 0;

    const tick = (time: number) => {
      const dt = Math.min(Math.max((time - lastTime) / 1000, 0), 0.05);
      lastTime = time;
      const pose = animator.update(dt);
      overlay.setPose(pose);
      if (animator.consumeArrived()) {
        void chrome.runtime
          .sendMessage({ type: CURSOR_MESSAGE_TYPES.arrived, moveSequence: lastSequence })
          .catch(() => {
            /* SW went away */
          });
      }
      rafId = animator.needsRender || pose.visible ? requestAnimationFrame(tick) : null;
    };

    const ensureLoop = () => {
      if (rafId === null) {
        lastTime = performance.now();
        rafId = requestAnimationFrame(tick);
      }
    };

    const applyState = (state: CursorState) => {
      if (!state.visible) {
        animator.hide();
        ensureLoop();
        return;
      }
      lastSequence = state.moveSequence;
      animator.moveTo({ x: state.x, y: state.y }, state.animateMovement);
      ensureLoop();
    };

    chrome.runtime.onMessage.addListener(
      (message: unknown, _sender: unknown, sendResponse: (response?: unknown) => void) => {
        if (typeof message !== 'object' || message === null) return;
        const type = (message as Record<string, unknown>).type;
        if (type === CURSOR_MESSAGE_TYPES.ping) {
          sendResponse({ ok: true });
          return;
        }
        if (type === CURSOR_MESSAGE_TYPES.state) {
          applyState((message as Record<string, unknown>).state as CursorState);
          sendResponse({ ok: true });
        }
      },
    );

    // Stateless page side: pull the SW-held state on (re)injection and on
    // bfcache restore so the cursor reappears after navigation.
    const pullState = () => {
      void chrome.runtime
        .sendMessage({ type: CURSOR_MESSAGE_TYPES.getState })
        .then((state: unknown) => {
          if (state && typeof state === 'object' && (state as CursorState).visible) {
            applyState(state as CursorState);
          }
        })
        .catch(() => {
          /* SW went away */
        });
    };
    pullState();
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) pullState();
    });
  },
});
