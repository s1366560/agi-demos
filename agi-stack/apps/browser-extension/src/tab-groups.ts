import type { ChromeApi } from './chrome-api';

export const TAB_GROUP_STORAGE_PREFIX = 'memstackTabGroup:';
export const DEFAULT_GROUP_COLOR = 'blue';

/**
 * Idempotent `key → groupId` tab-group registry, persisted in
 * `chrome.storage.local` so group ids survive service-worker restarts.
 * A stale stored id (group was closed) transparently recreates the group.
 */
export function createTabGroupRegistry(chrome: ChromeApi) {
  async function readStoredGroupId(key: string): Promise<number | undefined> {
    const items = await chrome.storage.local.get(TAB_GROUP_STORAGE_PREFIX + key);
    const value = items[TAB_GROUP_STORAGE_PREFIX + key];
    return typeof value === 'number' && Number.isInteger(value) ? value : undefined;
  }

  async function writeStoredGroupId(key: string, groupId: number): Promise<void> {
    await chrome.storage.local.set({ [TAB_GROUP_STORAGE_PREFIX + key]: groupId });
  }

  async function groupExists(groupId: number): Promise<boolean> {
    try {
      await chrome.tabGroups.get(groupId);
      return true;
    } catch {
      return false;
    }
  }

  async function createGroup(title: string, color?: string): Promise<number> {
    // chrome.tabs.group needs an anchor tab: create a background placeholder.
    // The sidecar is expected to close it or drive it once it assigns real tabs.
    const tab = await chrome.tabs.create({ url: 'about:blank', active: false });
    if (typeof tab.id !== 'number') {
      throw new Error('chrome.tabs.create returned no tab id for group anchor');
    }
    const groupId = await chrome.tabs.group({ tabIds: tab.id });
    await chrome.tabGroups.update(groupId, { title, color: color ?? DEFAULT_GROUP_COLOR });
    return groupId;
  }

  return {
    /** Idempotent per key: reuse a live group, recreate a stale one. */
    async ensureTabGroup(key: string, title: string, color?: string): Promise<number> {
      const stored = await readStoredGroupId(key);
      if (stored !== undefined && (await groupExists(stored))) {
        return stored;
      }
      const groupId = await createGroup(title, color);
      await writeStoredGroupId(key, groupId);
      return groupId;
    },
  };
}

export type TabGroupRegistry = ReturnType<typeof createTabGroupRegistry>;
