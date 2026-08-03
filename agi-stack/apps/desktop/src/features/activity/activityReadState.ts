import type { ActivityInboxEntry } from './activityInboxModel';

// 已读位:条目权威标识 -> 标记已读时的 Unix 毫秒时间。
export type ActivityReadState = Readonly<Record<string, number>>;

export const ACTIVITY_READ_STATE_STORAGE_PREFIX = 'agistack.desktop.activity-read-state.v1';

// 已读位持久化接口(后端持久化的接缝)。
// 当前实现为 localStorage;roadmap P0-1 的后端持久化属于后置项,
// 届时只需提供同一接口的远程实现并注入 useActivityInbox。
export interface ActivityReadStateStore {
  load(scopeKey: string): ActivityReadState;
  save(scopeKey: string, state: ActivityReadState): void;
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

// 条目更新时间晚于已读时间时重新视为未读(运行有新进展会再次点亮角标)。
export function activityEntryIsRead(
  entry: Pick<ActivityInboxEntry, 'id' | 'timestampMs'>,
  state: ActivityReadState,
): boolean {
  const readAt = state[entry.id];
  return typeof readAt === 'number' && readAt >= entry.timestampMs;
}

export function markActivityEntryRead(
  state: ActivityReadState,
  entryId: string,
  now: number,
): ActivityReadState {
  return { ...state, [entryId]: now };
}

export function markActivityEntriesRead(
  state: ActivityReadState,
  entries: readonly Pick<ActivityInboxEntry, 'id'>[],
  now: number,
): ActivityReadState {
  if (entries.length === 0) return state;
  const next: Record<string, number> = { ...state };
  for (const entry of entries) {
    next[entry.id] = now;
  }
  return next;
}

export function markActivityConversationRead(
  state: ActivityReadState,
  entries: readonly Pick<ActivityInboxEntry, 'id' | 'conversationId'>[],
  conversationId: string,
  now: number,
): ActivityReadState {
  return markActivityEntriesRead(
    state,
    entries.filter((entry) => entry.conversationId === conversationId),
    now,
  );
}

export function countUnreadActivityEntries(
  entries: readonly Pick<ActivityInboxEntry, 'id' | 'timestampMs'>[],
  state: ActivityReadState,
): number {
  return entries.reduce(
    (count, entry) => count + (activityEntryIsRead(entry, state) ? 0 : 1),
    0,
  );
}

function parseReadState(raw: string | null): ActivityReadState {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const state: Record<string, number> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'number' && Number.isFinite(value)) {
        state[key] = value;
      }
    }
    return state;
  } catch {
    return {};
  }
}

export function createLocalStorageReadStateStore(
  storage?: StorageLike,
): ActivityReadStateStore {
  const resolveStorage = (): StorageLike | null => {
    if (storage) return storage;
    try {
      return typeof window === 'undefined' ? null : window.localStorage;
    } catch {
      return null;
    }
  };
  return {
    load(scopeKey) {
      const target = resolveStorage();
      if (!target) return {};
      try {
        return parseReadState(
          target.getItem(`${ACTIVITY_READ_STATE_STORAGE_PREFIX}:${scopeKey}`),
        );
      } catch {
        return {};
      }
    },
    save(scopeKey, state) {
      const target = resolveStorage();
      if (!target) return;
      try {
        target.setItem(
          `${ACTIVITY_READ_STATE_STORAGE_PREFIX}:${scopeKey}`,
          JSON.stringify(state),
        );
      } catch {
        // 存储不可用(隐私模式/配额)时静默降级为会话内已读位。
      }
    },
  };
}
