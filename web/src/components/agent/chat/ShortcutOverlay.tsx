/**
 * ShortcutOverlay - Keyboard shortcut cheat sheet overlay
 *
 * Triggered by Cmd+/ (or Ctrl+/) or ? key. Shows all available shortcuts
 * in a clean modal overlay with categorized sections.
 */

import { memo, useEffect, useCallback, useState, useRef } from 'react';

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
  const [visible, setVisible] = useState(false);
  const isMac = typeof navigator !== 'undefined' && navigator.platform.includes('Mac');
  const mod = isMac ? 'Cmd' : 'Ctrl';

  const sections: ShortcutSection[] = [
    {
      title: t('agent.shortcuts.layout', 'Layout'),
      items: [
        { keys: [`${mod}+1`], description: t('agent.shortcuts.chatMode', 'Chat mode') },
        { keys: [`${mod}+2`], description: t('agent.shortcuts.codeMode', 'Code mode (split)') },
        {
          keys: [`${mod}+3`],
          description: t('agent.shortcuts.desktopMode', 'Desktop mode (split)'),
        },
        { keys: [`${mod}+4`], description: t('agent.shortcuts.focusMode', 'Focus mode') },
        { keys: [`${mod}+5`], description: t('agent.shortcuts.canvasMode', 'Canvas mode (split)') },
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
          keys: [`${mod}+F`],
          description: t('agent.shortcuts.searchChat', 'Search in conversation'),
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in"
      onClick={() => {
        setVisible(false);
      }}
      onKeyDown={handleOverlayKeyDown}
    >
      <div
        className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 w-full max-w-lg mx-4 overflow-hidden"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-700">
          <div className="flex items-center gap-2.5">
            <Keyboard size={20} className="text-primary" />
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {t('agent.shortcuts.title', 'Keyboard Shortcuts')}
            </h2>
          </div>
          <button
            ref={closeButtonRef}
            onClick={() => {
              setVisible(false);
            }}
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
                    className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700/30"
                  >
                    <span className="text-sm text-slate-600 dark:text-slate-300">
                      {item.description}
                    </span>
                    <div className="flex items-center gap-1">
                      {item.keys.map((key) => (
                        <kbd
                          key={key}
                          className="inline-flex items-center px-2 py-0.5 bg-slate-100 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-xs font-mono text-slate-500 dark:text-slate-400 min-w-[28px] justify-center"
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
          <p className="text-xs text-slate-400 dark:text-slate-500 text-center">
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
