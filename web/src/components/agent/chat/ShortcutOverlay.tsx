/**
 * ShortcutOverlay - Keyboard shortcut cheat sheet overlay
 *
 * Triggered by Cmd+/ (or Ctrl+/) or ? key. Shows all available shortcuts
 * in a clean modal overlay with categorized sections.
 */

import { memo, useEffect, useCallback, useId, useState, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { X, Keyboard } from 'lucide-react';

interface ShortcutItem {
  keys: string[];
  description: string;
}

interface ShortcutSection {
  title: string;
  items: ShortcutItem[];
}

export const ShortcutOverlay = memo(() => {
  const { t } = useTranslation();
  const titleId = useId();
  const footerId = useId();
  const [visible, setVisible] = useState(false);
  const isMac = typeof navigator !== 'undefined' && navigator.userAgent.includes('Mac');
  const mod = isMac ? 'Cmd' : 'Ctrl';

  const sections: ShortcutSection[] = [
    {
      title: t('agent.shortcuts.layout', 'Layout'),
      items: [
        { keys: [`${mod}+1`], description: t('agent.shortcuts.chatMode', 'Chat mode') },
        { keys: [`${mod}+2`], description: t('agent.shortcuts.taskMode', 'Task mode (split)') },
        { keys: [`${mod}+3`], description: t('agent.shortcuts.codeMode', 'Code mode (split)') },
        {
          keys: [`${mod}+4`],
          description: t('agent.shortcuts.canvasMode', 'Canvas mode (split)'),
        },
        { keys: [`${mod}+5`], description: t('agent.shortcuts.collabMode', 'Collab mode (split)') },
      ],
    },
    {
      title: t('agent.shortcuts.chat', 'Chat'),
      items: [
        { keys: ['Enter'], description: t('agent.shortcuts.sendMessage', 'Send message') },
        {
          keys: ['Shift+Enter'],
          description: t('agent.shortcuts.newLine', 'New line in message'),
        },
        {
          keys: ['/'],
          description: t('agent.shortcuts.focusInput', 'Focus input / Slash commands'),
        },
        { keys: ['j / k'], description: t('agent.shortcuts.navMessages', 'Navigate messages') },
        {
          keys: ['c'],
          description: t('agent.shortcuts.copyMessage', 'Copy focused message'),
        },
        {
          keys: [`${mod}+F`],
          description: t('agent.shortcuts.searchChat', 'Search in conversation'),
        },
        {
          keys: ['Shift+Tab'],
          description: t('agent.shortcuts.planMode', 'Toggle Plan Mode'),
        },
        { keys: ['Esc'], description: t('agent.shortcuts.cancelCommand', 'Cancel / close') },
      ],
    },
    {
      title: t('agent.shortcuts.general', 'General'),
      items: [
        {
          keys: [`${mod}+/`],
          description: t('agent.shortcuts.showShortcuts', 'Show this overlay'),
        },
        {
          keys: [`${mod}+V`],
          description: t('agent.shortcuts.pasteFiles', 'Paste files from clipboard'),
        },
      ],
    },
  ];

  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Cmd+/ or Ctrl+/ to toggle
    if ((e.metaKey || e.ctrlKey) && e.key === '/') {
      e.preventDefault();
      setVisible((v) => !v);
      return;
    }
    // Escape to close
    if (e.key === 'Escape') {
      setVisible(false);
    }
  }, []);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleKeyDown]);

  // Auto-focus close button when overlay opens
  useEffect(() => {
    if (visible) {
      const timer = setTimeout(() => {
        closeButtonRef.current?.focus();
      }, 50);
      return () => {
        clearTimeout(timer);
      };
    }
    return undefined;
  }, [visible]);

  // Focus trap: keep Tab cycling within the overlay
  const handleOverlayKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      closeButtonRef.current?.focus();
    }
    if (e.key === 'Escape') {
      setVisible(false);
    }
  }, []);

  if (!visible) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 animate-fade-in"
      onClick={() => {
        setVisible(false);
      }}
      onKeyDown={handleOverlayKeyDown}
    >
      <div
        className="mx-4 w-full max-w-lg overflow-hidden rounded-lg border border-slate-200 bg-slate-50 shadow-lg dark:border-slate-700 dark:bg-slate-900"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={footerId}
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-700">
          <div className="flex items-center gap-2.5">
            <Keyboard size={20} className="text-primary" aria-hidden="true" />
            <h2 id={titleId} className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {t('agent.shortcuts.title', 'Keyboard Shortcuts')}
            </h2>
          </div>
          <button
            type="button"
            ref={closeButtonRef}
            onClick={() => {
              setVisible(false);
            }}
            aria-label={t('agent.shortcuts.close', 'Close keyboard shortcuts')}
            title={t('agent.shortcuts.close', 'Close keyboard shortcuts')}
            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-5 max-h-[60vh] overflow-y-auto">
          {sections.map((section) => (
            <div key={section.title}>
              <h3 className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-2.5">
                {section.title}
              </h3>
              <div className="space-y-1.5">
                {section.items.map((item, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-lg px-2 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
                  >
                    <span className="text-sm text-slate-600 dark:text-slate-300">
                      {item.description}
                    </span>
                    <div className="flex items-center gap-1">
                      {item.keys.map((key) => (
                        <kbd
                          key={key}
                          className="inline-flex min-w-7 items-center justify-center rounded border border-slate-200 bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400"
                        >
                          {key}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-900/30">
          <p id={footerId} className="text-xs text-slate-400 dark:text-slate-500 text-center">
            {t('agent.shortcuts.footer', 'Press {{key}} to toggle this overlay', {
              key: `${mod}+/`,
            })}
          </p>
        </div>
      </div>
    </div>
  );
});

ShortcutOverlay.displayName = 'ShortcutOverlay';
