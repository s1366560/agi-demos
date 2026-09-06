import { useEffect, type RefObject } from 'react';

/** Restore the captured background even when authentication removes its shell. */
export function useDesktopModalBackgroundV2(
  shellRef: RefObject<HTMLElement | null>,
  enabled: boolean
): void {
  useEffect(() => {
    const shell = shellRef.current;
    if (!enabled || shell === null) return;
    const backgroundRoots = [
      ...new Set([document.getElementById('root'), shell.parentElement, shell]),
    ].filter((element): element is HTMLElement => element instanceof HTMLElement);
    const captured = backgroundRoots.map((element) => ({
      element,
      ariaHidden: element.getAttribute('aria-hidden'),
      inert: element.getAttribute('inert'),
    }));
    for (const { element } of captured) {
      element.setAttribute('aria-hidden', 'true');
      element.setAttribute('inert', '');
    }
    return () => {
      for (const { element, ariaHidden, inert } of captured) {
        if (ariaHidden === null) element.removeAttribute('aria-hidden');
        else element.setAttribute('aria-hidden', ariaHidden);
        if (inert === null) element.removeAttribute('inert');
        else element.setAttribute('inert', inert);
      }
    };
  }, [enabled, shellRef]);
}
