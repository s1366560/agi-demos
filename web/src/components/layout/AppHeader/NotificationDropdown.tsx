/**
 * NotificationDropdown — bell + persistent inbox panel.
 *
 * Composes the existing `useNotificationStore` (server-backed) with a
 * routa-style dropdown UI: unread count badge, type icon, relative time,
 * mark-all-read, and click-to-navigate via `action_url`.
 *
 * Keeps `AppHeader.Notifications` as the bare bell primitive; this component
 * is the higher-level shell to drop into layouts that want the full inbox.
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

function formatRelative(now: number, iso: string): string {
  const diff = now - new Date(iso).getTime();
  if (Number.isNaN(diff) || diff < 0) return 'now';
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${String(mins)}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${String(hrs)}h`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${String(days)}d`;
  return new Date(iso).toLocaleDateString();
}

export function NotificationDropdown({
  className,
  pollIntervalMs = 60_000,
  viewAllPath,
}: NotificationDropdownProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const notifications = useNotificationStore((s) => s.notifications);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const isLoading = useNotificationStore((s) => s.isLoading);
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

  // Click outside / Escape to close.
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const visibleItems = useMemo(() => notifications.slice(0, 20), [notifications]);

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
        type="button"
        onClick={() => {
          setOpen((prev) => !prev);
        }}
        aria-label={t('notifications.title', 'Notifications')}
        aria-haspopup="true"
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
          role="dialog"
          aria-label={t('notifications.title', 'Notifications')}
          className="absolute right-0 top-full z-50 mt-2 w-[22rem] overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900"
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
              <div className="px-3 py-6 text-center text-xs text-slate-400">
                {t('common.loading', 'Loading…')}
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
                          {formatRelative(now, n.created_at)}
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
          </div>
        </div>
      )}
    </div>
  );
}
