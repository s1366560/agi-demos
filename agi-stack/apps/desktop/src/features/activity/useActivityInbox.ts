import { useCallback, useEffect, useMemo, useState } from 'react';

import type { ProjectWorkItem } from '../../types';
import {
  buildActivityInboxEntries,
  groupActivityEntries,
  type ActivityInboxEntry,
  type ActivityInboxGroup,
} from './activityInboxModel';
import {
  activityEntryIsRead,
  countUnreadActivityEntries,
  createLocalStorageReadStateStore,
  markActivityConversationRead,
  markActivityEntriesRead,
  markActivityEntryRead,
  type ActivityReadState,
  type ActivityReadStateStore,
} from './activityReadState';

const defaultStore = createLocalStorageReadStateStore();

export type UseActivityInboxOptions = {
  items: ProjectWorkItem[];
  // 已读位的作用域(租户 + 项目),切换作用域时互不串扰。
  scopeKey: string;
  store?: ActivityReadStateStore;
};

export type ActivityInboxController = {
  entries: ActivityInboxEntry[];
  groups: ActivityInboxGroup[];
  unreadCount: number;
  isEntryRead: (entry: ActivityInboxEntry) => boolean;
  markRead: (entryId: string) => void;
  markAllRead: () => void;
  markConversationRead: (conversationId: string) => void;
};

export function useActivityInbox({
  items,
  scopeKey,
  store = defaultStore,
}: UseActivityInboxOptions): ActivityInboxController {
  const [readState, setReadState] = useState<ActivityReadState>(() => store.load(scopeKey));

  useEffect(() => {
    setReadState(store.load(scopeKey));
  }, [scopeKey, store]);

  const entries = useMemo(() => buildActivityInboxEntries(items), [items]);

  const update = useCallback(
    (updater: (current: ActivityReadState) => ActivityReadState) => {
      setReadState((current) => {
        const next = updater(current);
        if (next !== current) store.save(scopeKey, next);
        return next;
      });
    },
    [scopeKey, store],
  );

  const markRead = useCallback(
    (entryId: string) => {
      update((current) => markActivityEntryRead(current, entryId, Date.now()));
    },
    [update],
  );

  const markAllRead = useCallback(() => {
    update((current) => markActivityEntriesRead(current, entries, Date.now()));
  }, [update, entries]);

  const markConversationRead = useCallback(
    (conversationId: string) => {
      update((current) =>
        markActivityConversationRead(current, entries, conversationId, Date.now()),
      );
    },
    [update, entries],
  );

  const groups = useMemo(() => groupActivityEntries(entries), [entries]);
  const unreadCount = useMemo(
    () => countUnreadActivityEntries(entries, readState),
    [entries, readState],
  );
  const isEntryRead = useCallback(
    (entry: ActivityInboxEntry) => activityEntryIsRead(entry, readState),
    [readState],
  );

  return {
    entries,
    groups,
    unreadCount,
    isEntryRead,
    markRead,
    markAllRead,
    markConversationRead,
  };
}
