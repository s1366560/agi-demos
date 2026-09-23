import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

type ModalDialogOptions = {
  active?: boolean;
  initialFocusRef?: RefObject<HTMLElement | null>;
  nested?: boolean;
  returnFocusSelector?: string;
  onClose: () => void;
};

function focusableElements(dialog: HTMLElement): HTMLElement[] {
  return [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)].filter(
    (element) =>
      element.getClientRects().length > 0 && element.getAttribute('aria-hidden') !== 'true',
  );
}

export function useModalDialog({
  active = true,
  initialFocusRef,
  nested = false,
  returnFocusSelector,
  onClose,
}: ModalDialogOptions): RefObject<HTMLElement | null> {
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!active) return;
    const dialog = dialogRef.current;
    if (!dialog) return;

    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusInitial = () => {
      const requested = initialFocusRef?.current;
      const initial =
        requested && requested.getClientRects().length > 0
          ? requested
          : (focusableElements(dialog)[0] ?? dialog);
      initial.focus();
    };
    const focusFrame = window.requestAnimationFrame(focusInitial);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (nested) event.stopImmediatePropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      if (nested) event.stopPropagation();

      const focusable = focusableElements(dialog);
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;
      if (!dialog.contains(activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown, { capture: nested });
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener('keydown', handleKeyDown, { capture: nested });
      // Plugin surface updates can replace the opener during the close commit.
      // Restore only after that commit, resolving the current trigger if needed.
      window.requestAnimationFrame(() => {
        if (
          previouslyFocused?.isConnected &&
          previouslyFocused !== document.body &&
          !dialog.contains(previouslyFocused)
        ) {
          previouslyFocused.focus();
        } else if (returnFocusSelector) {
          document.querySelector<HTMLElement>(returnFocusSelector)?.focus();
        }
      });
    };
  }, [active, initialFocusRef, nested, returnFocusSelector]);

  return dialogRef;
}
