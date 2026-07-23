/**
 * Composer refill event bus.
 *
 * Message-level actions (Edit / Reply) need to inject text back into the
 * InputBar composer, which owns its own local state. A lightweight window
 * CustomEvent keeps the two decoupled (same pattern as searchEvents.ts).
 */

export const AGENT_COMPOSER_REFILL_EVENT = 'memstack:agent-composer-refill';

export function requestComposerRefill(text: string): void {
  window.dispatchEvent(new CustomEvent(AGENT_COMPOSER_REFILL_EVENT, { detail: { text } }));
}

export function subscribeToComposerRefill(onRefill: (text: string) => void): () => void {
  const handler = (e: Event) => {
    const detail = (e as CustomEvent<{ text?: unknown } | null>).detail;
    if (typeof detail?.text === 'string') {
      onRefill(detail.text);
    }
  };
  window.addEventListener(AGENT_COMPOSER_REFILL_EVENT, handler);
  return () => {
    window.removeEventListener(AGENT_COMPOSER_REFILL_EVENT, handler);
  };
}
