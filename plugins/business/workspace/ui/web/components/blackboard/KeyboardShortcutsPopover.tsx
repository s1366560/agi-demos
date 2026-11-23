import React, { useEffect, useId, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Keyboard } from 'lucide-react';

import { KEYBOARD_HINTS } from './arrangementUtils';

export interface KeyboardShortcutsPopoverProps {
  moveMode: unknown;
}

export const KeyboardShortcutsPopover: React.FC<KeyboardShortcutsPopoverProps> = ({ moveMode }) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dialogTitleId = useId();
  const shortcutsTitle = t('blackboard.arrangement.shortcutsTitle', {
    defaultValue: 'Keyboard shortcuts',
  });

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => {
          setIsOpen(!isOpen);
        }}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={shortcutsTitle}
        className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-light text-text-secondary transition hover:bg-surface-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:bg-surface-dark-alt dark:text-text-muted dark:hover:bg-white/5 dark:hover:text-text-inverse"
        title={shortcutsTitle}
      >
        <Keyboard className="h-4 w-4" />
      </button>

      {isOpen && (
        <div
          role="dialog"
          aria-labelledby={dialogTitleId}
          className="absolute right-0 top-full z-10 mt-2 w-64 md:w-80 rounded-xl border border-border-light bg-surface-light p-4 shadow-lg dark:border-border-dark dark:bg-surface-dark-alt"
        >
          <h3
            id={dialogTitleId}
            className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-primary dark:text-text-inverse"
          >
            {shortcutsTitle}
          </h3>
          <dl className="flex flex-col gap-2">
            {KEYBOARD_HINTS.map((hint) => (
              <div key={hint.keys} className="flex items-center justify-between gap-4">
                <dt className="text-xs text-text-secondary dark:text-text-muted">
                  {t(hint.labelKey, { defaultValue: hint.defaultLabel })}
                </dt>
                <dd>
                  <kbd className="inline-flex min-w-[20px] items-center justify-center rounded border border-border-light bg-background-light px-1 text-[10px] font-medium text-text-secondary dark:border-border-dark dark:bg-background-dark dark:text-text-muted">
                    {hint.keys}
                  </kbd>
                </dd>
              </div>
            ))}
          </dl>

          {!!moveMode && (
            <p className="mt-3 border-t border-border-light pt-3 text-xs text-text-secondary dark:border-border-dark dark:text-text-muted">
              {t('blackboard.arrangement.moveHint', {
                defaultValue: 'Use arrow keys to move the selected workstation.',
              })}
            </p>
          )}
        </div>
      )}
    </div>
  );
};
