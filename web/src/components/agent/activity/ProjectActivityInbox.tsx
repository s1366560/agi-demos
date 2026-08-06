import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Badge, Drawer } from 'antd';
import { Bell, CheckCheck, RefreshCw } from 'lucide-react';

import { ApiError, ApiErrorType } from '@/services/client/ApiError';
import {
  projectWorkService,
  type ActivityReadReceipt,
  type ActivityReadState,
  type ProjectWorkItem,
} from '@/services/projectWorkService';

import { Spinner } from '@/components/common/Spinner';

import {
  activityEntryIsRead,
  buildReadReceipt,
  countUnreadProjectWork,
  reconcilePendingActivityReceipts,
} from './projectActivityModel';

interface ProjectActivityInboxProps {
  tenantId: string;
  projectId: string;
  principalId: string;
  onOpenConversation: (conversationId: string) => void;
}

interface ActivityStorageScope {
  tenantId: string;
  projectId: string;
  principalId: string;
}

const pendingStorageKey = (scope: ActivityStorageScope): string =>
  `memstack.activity.pending-read.v2:${encodeURIComponent(scope.principalId)}:${encodeURIComponent(scope.tenantId)}:${encodeURIComponent(scope.projectId)}`;

const legacyPendingStorageKey = (projectId: string): string =>
  `memstack.activity.pending-read.v1:${projectId}`;

const readPending = (scope: ActivityStorageScope): ActivityReadReceipt[] => {
  try {
    const scopedRaw = window.localStorage.getItem(pendingStorageKey(scope));
    const legacyRaw = window.localStorage.getItem(legacyPendingStorageKey(scope.projectId));
    const scoped: unknown = scopedRaw ? JSON.parse(scopedRaw) : [];
    const legacy: unknown = legacyRaw ? JSON.parse(legacyRaw) : [];
    return [
      ...(Array.isArray(scoped) ? (scoped as ActivityReadReceipt[]) : []),
      ...(Array.isArray(legacy) ? (legacy as ActivityReadReceipt[]) : []),
    ];
  } catch {
    return [];
  }
};

const writePending = (scope: ActivityStorageScope, entries: ActivityReadReceipt[]): void => {
  try {
    if (entries.length === 0) {
      window.localStorage.removeItem(pendingStorageKey(scope));
      window.localStorage.removeItem(legacyPendingStorageKey(scope.projectId));
    } else {
      window.localStorage.setItem(pendingStorageKey(scope), JSON.stringify(entries));
    }
  } catch {
    // The server remains authoritative when browser storage is unavailable.
  }
};

const mergeReceipts = (
  current: ActivityReadReceipt[],
  incoming: ActivityReadReceipt[]
): ActivityReadReceipt[] => {
  const merged = new Map(current.map((entry) => [entry.entry_id, entry]));
  for (const entry of incoming) {
    const existing = merged.get(entry.entry_id);
    if (!existing || entry.entry_revision >= existing.entry_revision) {
      merged.set(entry.entry_id, entry);
    }
  }
  return [...merged.values()];
};

export function ProjectActivityInbox({
  tenantId,
  projectId,
  principalId,
  onOpenConversation,
}: ProjectActivityInboxProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ProjectWorkItem[]>([]);
  const [readState, setReadState] = useState<ActivityReadState | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const storageScope = useMemo(
    () => ({ tenantId, projectId, principalId }),
    [principalId, projectId, tenantId]
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [work, serverReadState] = await Promise.all([
        projectWorkService.list(projectId),
        projectWorkService.getReadState(projectId),
      ]);
      setItems(work.items);
      let resolvedReadState = serverReadState;
      const pending = reconcilePendingActivityReceipts(
        work.items,
        readPending(storageScope)
      );
      if (pending.length > 0) {
        resolvedReadState = await projectWorkService.updateReadState(projectId, {
          expected_authority_revision: serverReadState.authority_revision,
          entries: pending,
        });
        writePending(storageScope, []);
      } else {
        writePending(storageScope, []);
      }
      setReadState(resolvedReadState);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [projectId, storageScope]);

  useEffect(() => {
    void load();
  }, [load]);

  const unread = useMemo(
    () => countUnreadProjectWork(items, readState?.entries ?? []),
    [items, readState?.entries]
  );
  const receiptById = useMemo(
    () => new Map((readState?.entries ?? []).map((receipt) => [receipt.entry_id, receipt])),
    [readState?.entries]
  );

  const persistRead = useCallback(
    async (entries: ActivityReadReceipt[]) => {
      if (!readState || entries.length === 0) return false;
      setSyncing(true);
      setError(null);
      try {
        const next = await projectWorkService.updateReadState(projectId, {
          expected_authority_revision: readState.authority_revision,
          entries,
        });
        setReadState(next);
        writePending(storageScope, []);
        return true;
      } catch (caught) {
        if (caught instanceof ApiError && caught.isType(ApiErrorType.NETWORK)) {
          writePending(
            storageScope,
            mergeReceipts(readPending(storageScope), entries)
          );
        }
        setError(caught instanceof Error ? caught.message : String(caught));
        return false;
      } finally {
        setSyncing(false);
      }
    },
    [projectId, readState, storageScope]
  );

  const markAllRead = useCallback(() => {
    const now = new Date().toISOString();
    void persistRead(items.map((item) => buildReadReceipt(item, now)));
  }, [items, persistRead]);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
        }}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 px-2 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        aria-label={t('agent.activity.open', { defaultValue: 'Open Activity and My Work' })}
      >
        <Badge count={unread} size="small">
          <Bell size={15} />
        </Badge>
        <span className="hidden xl:inline">
          {t('agent.activity.title', { defaultValue: 'Activity' })}
        </span>
      </button>
      <Drawer
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        size="large"
        title={t('agent.activity.title', { defaultValue: 'Activity and My Work' })}
        extra={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading || syncing}
              aria-label={t('common.refresh', { defaultValue: 'Refresh' })}
              className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <RefreshCw size={15} />
            </button>
            <button
              type="button"
              onClick={markAllRead}
              disabled={unread === 0 || syncing}
              className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-40 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <CheckCheck size={14} />
              {t('agent.activity.markAllRead', { defaultValue: 'Mark all read' })}
            </button>
          </div>
        }
      >
        {loading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : error && items.length === 0 ? (
          <div role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            {t('agent.activity.loadFailed', { defaultValue: 'Activity could not be loaded.' })}
          </div>
        ) : items.length === 0 ? (
          <div className="py-12 text-center text-sm text-slate-500">
            {t('agent.activity.empty', { defaultValue: 'No work currently needs attention.' })}
          </div>
        ) : (
          <div className="space-y-2">
            {error && (
              <div role="status" className="rounded-md bg-amber-50 p-2 text-xs text-amber-700">
                {t('agent.activity.syncPending', {
                  defaultValue: 'Read state will retry when the authority is reachable.',
                })}
              </div>
            )}
            {items.map((item) => {
              const isRead = activityEntryIsRead(item, receiptById.get(item.id));
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    if (!isRead) {
                      void persistRead([buildReadReceipt(item, new Date().toISOString())]);
                    }
                    setOpen(false);
                    onOpenConversation(item.conversation_id);
                  }}
                  className={`w-full rounded-lg border p-3 text-left transition-colors ${
                    isRead
                      ? 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900'
                      : 'border-primary/30 bg-primary/5 dark:border-primary/40 dark:bg-primary/10'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                      {item.title}
                    </span>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                      {t(`agent.activity.group.${item.group}`, {
                        defaultValue: item.group,
                      })}
                    </span>
                  </div>
                  {item.run_summary?.completion_summary || item.summary ? (
                    <p className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">
                      {item.run_summary?.completion_summary || item.summary}
                    </p>
                  ) : null}
                  {item.run_summary?.input_tokens !== null &&
                  item.run_summary?.input_tokens !== undefined &&
                  item.run_summary.output_tokens !== null &&
                  item.run_summary.output_tokens !== undefined ? (
                    <p className="mt-2 text-[11px] text-slate-400">
                      {t('agent.activity.usage', {
                        defaultValue: '{{tokens}} tokens · {{cost}} {{currency}}',
                        tokens: item.run_summary.input_tokens + item.run_summary.output_tokens,
                        cost: item.run_summary.cost_usd ?? 0,
                        currency: 'USD',
                      })}
                    </p>
                  ) : null}
                </button>
              );
            })}
          </div>
        )}
      </Drawer>
    </>
  );
}
