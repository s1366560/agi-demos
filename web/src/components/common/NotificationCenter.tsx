/**
 * NotificationCenter — minimal in-app notification feed.
 *
 * Distilled from routa's notification provider. Keeps the latest 100
 * notifications in localStorage so the user can leave the workspace and
 * still see what happened. Dropped notifications when storage is unavailable
 * are silently held in memory (best-effort persistence is acceptable).
 *
 * Producers (e.g. SSE event handlers) call `pushNotification(...)`.
 * The Bell component subscribes via `useNotifications()` and renders.
 */

import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { Bell, CheckCheck, X } from 'lucide-react';

export type NotificationKind =
  | 'pr_review'
  | 'webhook'
  | 'task_complete'
  | 'hitl_pending'
  | 'error'
  | 'info';

export interface AppNotification {
  id: string;
  kind: NotificationKind;
  title: string;
  body?: string;
  createdAt: number;
  read: boolean;
  /** Optional deep-link target (e.g. workspace task id). */
  targetId?: string;
}

interface NotificationContextValue {
  notifications: AppNotification[];
  unreadCount: number;
  pushNotification: (n: Omit<AppNotification, 'id' | 'createdAt' | 'read'>) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  removeNotification: (id: string) => void;
  clearAll: () => void;
}

const STORAGE_KEY = 'memstack:notifications:v1';
const MAX_NOTIFICATIONS = 100;

const NotificationContext = createContext<NotificationContextValue | null>(null);

function loadFromStorage(): AppNotification[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as AppNotification[];
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(0, MAX_NOTIFICATIONS);
  } catch {
    return [];
  }
}

function saveToStorage(items: AppNotification[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_NOTIFICATIONS)));
  } catch {
    // Storage full / disabled — best effort.
  }
}

function makeId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `n_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

export interface NotificationProviderProps {
  children: ReactNode;
}

export const NotificationProvider = memo<NotificationProviderProps>(({ children }) => {
  const [notifications, setNotifications] = useState<AppNotification[]>(() => loadFromStorage());
  const persistRef = useRef<number | null>(null);

  // Persist with a small debounce so bursty pushes don't thrash storage.
  useEffect(() => {
    if (persistRef.current !== null) {
      window.clearTimeout(persistRef.current);
    }
    persistRef.current = window.setTimeout(() => {
      saveToStorage(notifications);
    }, 200);
    return () => {
      if (persistRef.current !== null) {
        window.clearTimeout(persistRef.current);
      }
    };
  }, [notifications]);

  const pushNotification = useCallback<NotificationContextValue['pushNotification']>((n) => {
    setNotifications((prev) => {
      const next: AppNotification = {
        ...n,
        id: makeId(),
        createdAt: Date.now(),
        read: false,
      };
      const merged = [next, ...prev];
      return merged.slice(0, MAX_NOTIFICATIONS);
    });
  }, []);

  const markRead = useCallback<NotificationContextValue['markRead']>((id) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id && !n.read ? { ...n, read: true } : n))
    );
  }, []);

  const markAllRead = useCallback<NotificationContextValue['markAllRead']>(() => {
    setNotifications((prev) => prev.map((n) => (n.read ? n : { ...n, read: true })));
  }, []);

  const removeNotification = useCallback<NotificationContextValue['removeNotification']>((id) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const clearAll = useCallback<NotificationContextValue['clearAll']>(() => {
    setNotifications([]);
  }, []);

  const unreadCount = useMemo(
    () => notifications.reduce((acc, n) => (n.read ? acc : acc + 1), 0),
    [notifications]
  );

  const value = useMemo<NotificationContextValue>(
    () => ({
      notifications,
      unreadCount,
      pushNotification,
      markRead,
      markAllRead,
      removeNotification,
      clearAll,
    }),
    [notifications, unreadCount, pushNotification, markRead, markAllRead, removeNotification, clearAll]
  );

  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>;
});

NotificationProvider.displayName = 'NotificationProvider';

export function useNotifications(): NotificationContextValue {
  const ctx = useContext(NotificationContext);
  if (ctx === null) {
    throw new Error('useNotifications must be used inside <NotificationProvider>');
  }
  return ctx;
}

const KIND_ACCENT: Record<NotificationKind, string> = {
  pr_review: 'bg-violet-500',
  webhook: 'bg-cyan-500',
  task_complete: 'bg-emerald-500',
  hitl_pending: 'bg-amber-500',
  error: 'bg-red-500',
  info: 'bg-slate-400',
};

function relativeTime(ms: number): string {
  const delta = Date.now() - ms;
  const sec = Math.round(delta / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

export interface NotificationCenterProps {
  className?: string;
}

export const NotificationCenter = memo<NotificationCenterProps>(({ className = '' }) => {
  const { notifications, unreadCount, markRead, markAllRead, removeNotification, clearAll } =
    useNotifications();
  const [open, setOpen] = useState(false);

  return (
    <div className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Notifications (${unreadCount} unread)`}
        aria-expanded={open}
        className="relative rounded-md p-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 text-[10px] font-semibold rounded-full bg-red-500 text-white">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 mt-2 w-[360px] max-h-[480px] overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-xl z-50 flex flex-col"
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200 dark:border-slate-700">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
              Notifications
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={markAllRead}
                disabled={unreadCount === 0}
                className="text-xs px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 inline-flex items-center gap-1"
              >
                <CheckCheck size={12} /> All read
              </button>
              <button
                type="button"
                onClick={clearAll}
                disabled={notifications.length === 0}
                className="text-xs px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40"
              >
                Clear
              </button>
            </div>
          </div>
          <div className="overflow-y-auto flex-1">
            {notifications.length === 0 ? (
              <div className="text-xs text-slate-500 dark:text-slate-400 px-3 py-8 text-center">
                No notifications yet.
              </div>
            ) : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {notifications.map((n) => (
                  <li
                    key={n.id}
                    className={`px-3 py-2 flex items-start gap-2 ${
                      n.read ? 'opacity-60' : 'bg-slate-50/60 dark:bg-slate-800/30'
                    }`}
                  >
                    <span className={`mt-1.5 inline-block h-2 w-2 rounded-full ${KIND_ACCENT[n.kind]}`} />
                    <button
                      type="button"
                      onClick={() => markRead(n.id)}
                      className="flex-1 text-left"
                    >
                      <div className="text-xs font-medium text-slate-800 dark:text-slate-100 truncate">
                        {n.title}
                      </div>
                      {n.body && (
                        <div className="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2">
                          {n.body}
                        </div>
                      )}
                      <div className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">
                        {relativeTime(n.createdAt)}
                      </div>
                    </button>
                    <button
                      type="button"
                      aria-label="Dismiss notification"
                      onClick={() => removeNotification(n.id)}
                      className="rounded p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
                    >
                      <X size={12} />
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
});

NotificationCenter.displayName = 'NotificationCenter';
