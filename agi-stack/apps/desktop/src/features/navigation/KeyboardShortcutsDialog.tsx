import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Cross2Icon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  detectShortcutPlatform,
  shortcutChordFor,
  shortcutChordSegments,
  shortcutGroups,
  type ShortcutPlatform,
} from './keyboardShortcutModel';
import './KeyboardShortcutsDialog.css';

function currentShortcutPlatform(): ShortcutPlatform {
  if (typeof navigator === 'undefined') return detectShortcutPlatform();
  return detectShortcutPlatform(navigator.userAgent, navigator.platform);
}

function getShortcutsDialogFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  const selectors = [
    'button:not(:disabled)',
    'input:not(:disabled)',
    'textarea:not(:disabled)',
    'select:not(:disabled)',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  return Array.from(container.querySelectorAll<HTMLElement>(selectors)).filter(
    (element) => element.getAttribute('aria-hidden') !== 'true',
  );
}

export function KeyboardShortcutsPanel({
  platform = currentShortcutPlatform(),
  onClose,
}: {
  platform?: ShortcutPlatform;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLElement>(null);
  const groups = shortcutGroups();

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.defaultPrevented || event.key !== 'Tab') return;
    const focusableElements = getShortcutsDialogFocusableElements(dialogRef.current);
    if (!focusableElements.length) return;
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    const activeElement = document.activeElement;

    if (event.shiftKey && activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
      return;
    }
    if (!event.shiftKey && activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  };

  return (
    <div className="shortcuts-backdrop" onMouseDown={onClose}>
      <section
        ref={dialogRef}
        className="shortcuts-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('shortcuts.title')}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="shortcuts-dialog__header">
          <h2 className="shortcuts-dialog__title">{t('shortcuts.title')}</h2>
          <button
            type="button"
            className="shortcuts-dialog__close"
            aria-label={t('common.close')}
            title={t('common.close')}
            onClick={onClose}
          >
            <Cross2Icon aria-hidden="true" />
          </button>
        </header>
        <div className="shortcuts-dialog__body">
          {groups.map(({ group, shortcuts }) => (
            <section className="shortcuts-group" key={group}>
              <h3 className="shortcuts-group__title">{t(`shortcuts.group.${group}`)}</h3>
              <ul className="shortcuts-group__list">
                {shortcuts.map((definition) => (
                  <li className="shortcuts-row" key={definition.id}>
                    <span className="shortcuts-row__label">{t(definition.labelKey)}</span>
                    <span className="shortcuts-row__chord">
                      {shortcutChordSegments(shortcutChordFor(definition, platform)).map(
                        (segment) => (
                          <kbd className="shortcuts-kbd" key={segment}>
                            {segment}
                          </kbd>
                        ),
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </section>
    </div>
  );
}

export function KeyboardShortcutsDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const restoreTargetRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreTargetRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      const target = restoreTargetRef.current;
      restoreTargetRef.current = null;
      if (target?.isConnected) {
        window.requestAnimationFrame(() => {
          if (target.isConnected) target.focus();
        });
      }
    };
  }, [open]);

  if (!open || typeof document === 'undefined') return null;
  return createPortal(<KeyboardShortcutsPanel onClose={onClose} />, document.body);
}
