/**
 * CommandPalette — Cmd/Ctrl+K command palette.
 *
 * Provides quick keyboard-driven access to:
 *  - Navigation destinations (top-nav items for the current tenant context)
 *  - Recent conversations (from conversationsStore)
 *  - Actions (new conversation, toggle theme, toggle language)
 *
 * Accessibility:
 *  - role="dialog" + aria-modal + aria-label
 *  - Input has role="combobox", aria-expanded, aria-controls, aria-activedescendant
 *  - Results list has role="listbox"; each item has role="option" + aria-selected
 *  - Focus trap: Tab cycles within palette; Escape closes; focus restored on close
 *  - Body scroll lock while open
 *
 * Architecture: standalone portal (not AppModal) because the palette UX is
 * distinct — flat, input-first, scrollable results, no title bar.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import {
  MessageSquarePlus,
  Moon,
  Sun,
  Languages,
  ArrowRight,
  type LucideIcon,
} from 'lucide-react';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useThemeStore } from '@/stores/theme';

import { deriveTopNavigationItems } from '@/config/navigation';
import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  tenantId?: string | undefined;
  projectId?: string | undefined;
}

interface CommandItem {
  id: string;
  label: string;
  hint?: string | undefined;
  icon?: LucideIcon | undefined;
  group: string;
  action: () => void;
}

/** Normalize text for fuzzy substring matching. */
function normalize(text: string): string {
  return text.toLowerCase().trim();
}

/** Score how well an item matches a query (higher = better, 0 = no match). */
function scoreItem(label: string, query: string): number {
  if (!query) return 1;
  const nLabel = normalize(label);
  const nQuery = normalize(query);
  if (nLabel.startsWith(nQuery)) return 3;
  if (nLabel.includes(nQuery)) return 2;
  // Word-boundary match
  const words = nLabel.split(/\s+/);
  if (words.some((w) => w.startsWith(nQuery))) return 1.5;
  return 0;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  open,
  onClose,
  tenantId,
  projectId,
}) => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  const conversations = useConversationsStore((s) => s.conversations);
  const computedTheme = useThemeStore((s) => s.computedTheme);
  const setTheme = useThemeStore((s) => s.setTheme);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  // Track open transitions to reset palette state (React "adjust state during render" pattern).
  const [prevOpen, setPrevOpen] = useState(false);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setQuery('');
      setActiveIndex(0);
    }
  }

  // Side-effects when palette opens: focus input + lock body scroll.
  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Restore focus on close.
  useEffect(() => {
    if (!open && previouslyFocused.current) {
      previouslyFocused.current.focus();
    }
  }, [open]);

  const close = useCallback(() => {
    onClose();
  }, [onClose]);

  // Build all command items.
  const allItems = useMemo<CommandItem[]>(() => {
    const items: CommandItem[] = [];

    // Actions group
    const actions: CommandItem[] = [
      {
        id: 'action-new-conversation',
        label: t('commandPalette.actions.newConversation', {
          defaultValue: 'New conversation',
        }),
        icon: MessageSquarePlus,
        group: t('commandPalette.groups.actions', { defaultValue: 'Actions' }),
        action: () => {
          navigate(buildAgentWorkspacePath({ tenantId, projectId }));
          close();
        },
      },
      {
        id: 'action-toggle-theme',
        label:
          computedTheme === 'dark'
            ? t('commandPalette.actions.switchToLight', {
                defaultValue: 'Switch to light theme',
              })
            : t('commandPalette.actions.switchToDark', {
                defaultValue: 'Switch to dark theme',
              }),
        icon: computedTheme === 'dark' ? Sun : Moon,
        group: t('commandPalette.groups.actions', { defaultValue: 'Actions' }),
        action: () => {
          setTheme(computedTheme === 'dark' ? 'light' : 'dark');
          close();
        },
      },
      {
        id: 'action-toggle-language',
        label:
          i18n.language === 'zh-CN'
            ? t('commandPalette.actions.switchToEnglish', {
                defaultValue: 'Switch to English',
              })
            : t('commandPalette.actions.switchToChinese', {
                defaultValue: '切换到中文',
              }),
        icon: Languages,
        group: t('commandPalette.groups.actions', { defaultValue: 'Actions' }),
        action: () => {
          void i18n.changeLanguage(i18n.language === 'zh-CN' ? 'en-US' : 'zh-CN');
          close();
        },
      },
    ];
    items.push(...actions);

    // Navigation group
    const navContext = tenantId ? 'tenant' : ('tenant' as const);
    const navItems = deriveTopNavigationItems(navContext, { tenantId, projectId });
    for (const nav of navItems) {
      const label = t(nav.label, { defaultValue: nav.label });
      items.push({
        id: `nav-${nav.id}`,
        label,
        hint: nav.relativePath,
        group: t('commandPalette.groups.navigation', { defaultValue: 'Navigation' }),
        action: () => {
          navigate(nav.path);
          close();
        },
      });
    }

    // Recent conversations group
    const recentConvs = conversations.slice(0, 8);
    for (const conv of recentConvs) {
      items.push({
        id: `conv-${conv.id}`,
        label: conv.title || conv.id,
        hint: conv.updated_at
          ? new Date(conv.updated_at).toLocaleDateString()
          : undefined,
        icon: ArrowRight,
        group: t('commandPalette.groups.recentConversations', {
          defaultValue: 'Recent conversations',
        }),
        action: () => {
          navigate(
            buildAgentWorkspacePath({
              tenantId,
              conversationId: conv.id,
              projectId: conv.project_id,
              workspaceId: conv.workspace_id,
            }),
          );
          close();
        },
      });
    }

    return items;
  }, [t, i18n, navigate, close, tenantId, projectId, conversations, computedTheme, setTheme]);

  // Filter + sort items by query.
  const filteredItems = useMemo(() => {
    if (!query.trim()) return allItems;
    return allItems
      .map((item) => ({ item, score: scoreItem(item.label, query) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .map((x) => x.item);
  }, [allItems, query]);

  // Group filtered items (preserve order, group consecutive same-group items).
  const grouped = useMemo(() => {
    const groups: { group: string; items: CommandItem[] }[] = [];
    for (const item of filteredItems) {
      const last = groups[groups.length - 1];
      if (last && last.group === item.group) {
        last.items.push(item);
      } else {
        groups.push({ group: item.group, items: [item] });
      }
    }
    return groups;
  }, [filteredItems]);

  // Derived safe active index (avoids setState-in-effect clamp).
  const safeActiveIndex = Math.min(activeIndex, Math.max(0, filteredItems.length - 1));

  // Scroll active item into view.
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-cp-index="${safeActiveIndex}"]`,
    );
    el?.scrollIntoView({ block: 'nearest' });
  }, [safeActiveIndex, open]);

  const executeItem = useCallback(
    (item: CommandItem | undefined) => {
      if (!item) return;
      item.action();
    },
    [],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % Math.max(1, filteredItems.length));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIndex((i) =>
          i === 0 ? Math.max(0, filteredItems.length - 1) : i - 1,
        );
      } else if (e.key === 'Enter') {
        e.preventDefault();
        executeItem(filteredItems[safeActiveIndex]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        close();
      } else if (e.key === 'Tab') {
        // Trap focus: keep it on the input.
        e.preventDefault();
        inputRef.current?.focus();
      }
    },
    [filteredItems, safeActiveIndex, executeItem, close],
  );

  if (!open) return null;

  const listboxId = 'command-palette-listbox';
  const inputId = 'command-palette-input';

  // Flatten grouped items for index-based lookup.
  let flatIndex = -1;

  return createPortal(
    <div
      className="app-modal__backdrop fixed inset-0 flex items-start justify-center bg-[var(--color-overlay-backdrop,#080c12cc)] px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('commandPalette.title', { defaultValue: 'Command palette' })}
        className="app-modal__panel flex max-h-[70vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-[var(--color-border,#242d3a)] bg-[var(--color-panel,#0d121a)] text-[var(--color-text,#e7edf6)] shadow-2xl"
      >
        {/* Input */}
        <div className="flex items-center gap-3 border-b border-[var(--color-border,#242d3a)] px-4 py-3">
          <input
            ref={inputRef}
            id={inputId}
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls={listboxId}
            aria-autocomplete="list"
            aria-activedescendant={
              filteredItems[safeActiveIndex]
                ? `cp-opt-${filteredItems[safeActiveIndex].id}`
                : undefined
            }
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={onKeyDown}
            placeholder={t('commandPalette.placeholder', {
              defaultValue: 'Search commands, pages, conversations…',
            })}
            className="flex-1 bg-transparent text-base text-[var(--color-text,#e7edf6)] placeholder:text-[var(--color-muted,#8996a9)] outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="shrink-0 rounded border border-[var(--color-border,#334154)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-muted,#8996a9)]">
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div
          ref={listRef}
          id={listboxId}
          role="listbox"
          aria-label={t('commandPalette.resultsLabel', {
            defaultValue: 'Command results',
          })}
          className="flex-1 overflow-y-auto overscroll-contain py-2"
        >
          {filteredItems.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-[var(--color-muted,#8996a9)]">
              {t('commandPalette.noResults', {
                defaultValue: 'No results found',
              })}
            </div>
          ) : (
            grouped.map((group) => (
              <div key={group.group} className="mb-1">
                <div className="px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted,#8996a9)]">
                  {group.group}
                </div>
                {group.items.map((item) => {
                  flatIndex += 1;
                  const idx = flatIndex;
                  const isActive = idx === safeActiveIndex;
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.id}
                      id={`cp-opt-${item.id}`}
                      type="button"
                      role="option"
                      aria-selected={isActive}
                      data-cp-index={idx}
                      onMouseEnter={() => { setActiveIndex(idx); }}
                      onClick={() => { executeItem(item); }}
                      className={`flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
                        isActive
                          ? 'bg-[var(--color-panel-2,#111720)] text-[var(--color-text,#e7edf6)]'
                          : 'text-[var(--color-text,#e7edf6)]'
                      }`}
                    >
                      {Icon ? (
                        <Icon className="h-4 w-4 shrink-0 text-[var(--color-muted,#8996a9)]" />
                      ) : (
                        <span className="h-4 w-4 shrink-0" />
                      )}
                      <span className="flex-1 truncate">{item.label}</span>
                      {item.hint ? (
                        <span className="shrink-0 text-xs text-[var(--color-muted,#8996a9)]">
                          {item.hint}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="flex items-center justify-between gap-4 border-t border-[var(--color-border,#242d3a)] px-4 py-2 text-[11px] text-[var(--color-muted,#8996a9)]">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-[var(--color-border,#334154)] px-1">↑</kbd>
              <kbd className="rounded border border-[var(--color-border,#334154)] px-1">↓</kbd>
              {t('commandPalette.hints.navigate', { defaultValue: 'navigate' })}
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-[var(--color-border,#334154)] px-1">↵</kbd>
              {t('commandPalette.hints.select', { defaultValue: 'select' })}
            </span>
          </div>
          <span>{filteredItems.length} results</span>
        </div>
      </div>
    </div>,
    document.body,
  );
};

/**
 * useCommandPaletteOpen — hook that manages Cmd/Ctrl+K global listener + open state.
 * Returns [open, setOpen] for consumers to also trigger the palette from a button.
 */
export function useCommandPaletteOpen(): [boolean, React.Dispatch<React.SetStateAction<boolean>>] {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener('keydown', handler);
    return () => {
      document.removeEventListener('keydown', handler);
    };
  }, []);

  return [open, setOpen];
}
