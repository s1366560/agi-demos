/**
 * NotificationDropdown — bell + persistent inbox panel.
 *
 * Composes the existing `useNotificationStore` (server-backed) with a
 * routa-style dropdown UI: unread count badge, type icon, relative time,
 * mark-all-read, and click-to-navigate via `action_url`.
 *
 * Higher-level shell for layouts that want the full inbox (used by
 * `TenantHeader`).
 */

import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { AlertTriangle, Bell, BellRing, CheckCheck, Inbox, Info, Trash2 } from 'lucide-react';

import { useNotificationStore } from '@/stores/notification';

interface NotificationDropdownProps {
  /** Optional anchor; defaults to bell icon. */
  className?: string;
  /** Polling interval in ms; 0 disables polling. Defaults to 60s. */
  pollIntervalMs?: number;
  /** Path to navigate to for "view all"; if omitted, footer is hidden. */
  viewAllPath?: string;
}

const TYPE_ICON: Record<string, ReactElement> = {
  task: <CheckCheck className="w-3.5 h-3.5 text-emerald-500" />,
  hitl: <BellRing className="w-3.5 h-3.5 text-amber-500" />,
  webhook: <Inbox className="w-3.5 h-3.5 text-sky-500" />,
  error: <AlertTriangle className="w-3.5 h-3.5 text-rose-500" />,
  info: <Info className="w-3.5 h-3.5 text-slate-400" />,
};

function formatRelative(
  now: number,
  iso: string,
  t: ReturnType<typeof useTranslation>['t'],
  locale: string
): string {
  const diff = now - new Date(iso).getTime();
  if (Number.isNaN(diff) || diff < 0) return t('common.time.justNow', 'just now');
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return t('common.time.justNow', 'just now');
  if (mins < 60) return t('common.time.minutesAgo', '{{count}}m ago', { count: mins });
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return t('common.time.hoursAgo', '{{count}}h ago', { count: hrs });
  const days = Math.floor(hrs / 24);
  if (days < 30) return t('common.time.daysAgo', '{{count}}d ago', { count: days });
  return new Date(iso).toLocaleDateString(locale);
}

const PAGE_SIZE = 20;

export function NotificationDropdown({
  className,
  pollIntervalMs = 60_000,
  viewAllPath,
}: NotificationDropdownProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  // Set when the panel is opened from the keyboard; focus moves into it once rendered.
  const focusPanelOnOpenRef = useRef(false);

  const notifications = useNotificationStore((s) => s.notifications);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const isLoading = useNotificationStore((s) => s.isLoading);
  const error = useNotificationStore((s) => s.error);
  const fetchNotifications = useNotificationStore((s) => s.fetchNotifications);
  const markAsRead = useNotificationStore((s) => s.markAsRead);
  const markAllAsRead = useNotificationStore((s) => s.markAllAsRead);
  const deleteNotification = useNotificationStore((s) => s.deleteNotification);

  // Initial load + polling.
  useEffect(() => {
    void fetchNotifications();
    if (!pollIntervalMs) return undefined;
    const id = setInterval(() => {
      void fetchNotifications();
    }, pollIntervalMs);
    return () => {
      clearInterval(id);
    };
  }, [fetchNotifications, pollIntervalMs]);

  // Tick "now" while open so relative times stay fresh.
  useEffect(() => {
    if (!open) return undefined;
    const id = setInterval(() => {
      setNow(Date.now());
    }, 30_000);
    return () => {
      clearInterval(id);
    };
  }, [open]);

  // Click outside / Escape to close (Escape returns focus to the trigger).
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  // Move focus into the panel when it was opened from the keyboard.
  useEffect(() => {
    if (!open || !focusPanelOnOpenRef.current) return;
    focusPanelOnOpenRef.current = false;
    panelRef.current?.querySelector<HTMLButtonElement>('button:not([disabled])')?.focus();
  }, [open]);

  // Arrow keys cycle focus through the panel's interactive elements.
  const handlePanelKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const panel = panelRef.current;
    if (!panel) return;
    const focusables = Array.from(
      panel.querySelectorAll<HTMLButtonElement>('button:not([disabled])')
    );
    if (focusables.length === 0) return;
    event.preventDefault();
    const currentIndex = focusables.findIndex((el) => el === document.activeElement);
    const nextIndex =
      event.key === 'ArrowDown'
        ? currentIndex < 0
          ? 0
          : (currentIndex + 1) % focusables.length
        : currentIndex < 0
          ? focusables.length - 1
          : (currentIndex - 1 + focusables.length) % focusables.length;
    focusables[nextIndex]?.focus();
  };

  // ArrowDown on the trigger opens the panel and moves focus into it.
  const handleTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowDown') return;
    event.preventDefault();
    if (open) {
      panelRef.current?.querySelector<HTMLButtonElement>('button:not([disabled])')?.focus();
    } else {
      focusPanelOnOpenRef.current = true;
      setOpen(true);
    }
  };

  const visibleItems = useMemo(
    () => notifications.slice(0, visibleCount),
    [notifications, visibleCount]
  );
  const hasMore = notifications.length > visibleCount;
  const locale = i18n.resolvedLanguage || i18n.language || 'en-US';
  const triggerLabel =
    unreadCount > 0
      ? t('notifications.titleWithUnread', 'Notifications, {{count}} unread', {
          count: unreadCount,
        })
      : t('notifications.title', 'Notifications');

  const handleItemClick = async (id: string, actionUrl: string | undefined) => {
    await markAsRead(id);
    if (actionUrl) {
      setOpen(false);
      // Internal vs external link.
      if (actionUrl.startsWith('http')) {
        window.open(actionUrl, '_blank', 'noopener,noreferrer');
      } else {
        void navigate(actionUrl);
      }
    }
  };

  return (
    <div ref={containerRef} className={`relative ${className ?? ''}`.trim()}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => {
          setOpen((prev) => !prev);
        }}
        onKeyDown={handleTriggerKeyDown}
        aria-label={triggerLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="relative flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 inline-flex min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold leading-4 text-white">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label={t('notifications.title', 'Notifications')}
          onKeyDown={handlePanelKeyDown}
          className="absolute right-0 top-full z-50 mt-2 w-[22rem] overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2 dark:border-slate-800">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
              {t('notifications.title', 'Notifications')}
              {unreadCount > 0 && (
                <span className="ml-1.5 text-[10px] font-medium text-rose-500">
                  {unreadCount} {t('notifications.unread', 'unread')}
                </span>
              )}
            </span>
            <div className="flex items-center gap-2">
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    void markAllAsRead();
                  }}
                  className="text-[11px] text-blue-600 hover:underline dark:text-blue-400"
                >
                  {t('notifications.markAllRead', 'Mark all read')}
                </button>
              )}
              {viewAllPath && (
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    void navigate(viewAllPath);
                  }}
                  className="text-[11px] text-slate-500 hover:underline dark:text-slate-400"
                >
                  {t('notifications.viewAll', 'View all')}
                </button>
              )}
            </div>
          </header>

          <div className="max-h-[24rem] overflow-y-auto">
            {isLoading && visibleItems.length === 0 ? (
              <div className="space-y-2 px-3 py-3" role="status">
                {[0, 1, 2].map((row) => (
                  <div key={row} className="flex items-start gap-2">
                    <span className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-pulse rounded-full bg-slate-200 motion-reduce:animate-none dark:bg-slate-700" />
                    <span className="flex-1 space-y-1.5">
                      <span className="block h-3 w-3/4 animate-pulse rounded bg-slate-200 motion-reduce:animate-none dark:bg-slate-700" />
                      <span className="block h-2.5 w-full animate-pulse rounded bg-slate-100 motion-reduce:animate-none dark:bg-slate-800" />
                    </span>
                  </div>
                ))}
                <span className="sr-only">{t('common.loading', 'Loading…')}</span>
              </div>
            ) : error && visibleItems.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-3 py-8 text-center">
                <AlertTriangle className="h-5 w-5 text-rose-500" />
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('notifications.loadFailed', 'Failed to load notifications')}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    void fetchNotifications();
                  }}
                  className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  {t('common.retry', 'Retry')}
                </button>
              </div>
            ) : visibleItems.length === 0 ? (
              <div className="flex flex-col items-center gap-1.5 px-3 py-8 text-center text-xs text-slate-400">
                <Inbox className="h-5 w-5" />
                {t('notifications.empty', 'No notifications')}
              </div>
            ) : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {visibleItems.map((n) => (
                  <li
                    key={n.id}
                    className={`group relative flex items-stretch transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60 ${
                      n.is_read ? '' : 'bg-blue-50/40 dark:bg-blue-900/10'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        void handleItemClick(n.id, n.action_url);
                      }}
                      className="flex flex-1 items-start gap-2 px-3 py-2.5 text-left"
                    >
                      <span className="mt-0.5 shrink-0">{TYPE_ICON[n.type] ?? TYPE_ICON.info}</span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className="truncate text-xs font-medium text-slate-800 dark:text-slate-100">
                            {n.title}
                          </span>
                          {!n.is_read && (
                            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                          )}
                        </span>
                        <span className="mt-0.5 line-clamp-2 block text-[11px] text-slate-500 dark:text-slate-400">
                          {n.message}
                        </span>
                        <span className="mt-1 block text-[10px] text-slate-400">
                          {formatRelative(now, n.created_at, t, locale)}
                        </span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void deleteNotification(n.id);
                      }}
                      className="invisible mr-1 mt-1.5 shrink-0 self-start rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-rose-500 group-hover:visible dark:hover:bg-slate-700"
                      aria-label={t('common.delete', 'Delete')}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {hasMore && (
              <div className="border-t border-slate-100 px-3 py-2 text-center dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => {
                    setVisibleCount((count) => count + PAGE_SIZE);
                  }}
                  className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  {t('notifications.loadMore', 'Load more ({{count}} remaining)', {
                    count: notifications.length - visibleCount,
                  })}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
