/**
 * useTurnCollapse - Per-conversation collapsed-turn state with localStorage
 * persistence so refreshes don't lose the user's folding.
 *
 * Key shape: `routa.turn-collapse:<conversationId>` => JSON array of turn ids.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

const STORAGE_PREFIX = 'memstack:turn-collapse:';

function storageKey(conversationId: string | null | undefined): string | null {
  if (!conversationId) return null;
  return `${STORAGE_PREFIX}${conversationId}`;
}

function readSet(conversationId: string | null | undefined): Set<string> {
  const key = storageKey(conversationId);
  if (!key || typeof window === 'undefined') return new Set();
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return new Set(parsed.filter((v): v is string => typeof v === 'string'));
    }
  } catch {
    // ignore corrupted storage
  }
  return new Set();
}

function writeSet(conversationId: string | null | undefined, values: Set<string>): void {
  const key = storageKey(conversationId);
  if (!key || typeof window === 'undefined') return;
  try {
    if (values.size === 0) {
      window.localStorage.removeItem(key);
    } else {
      window.localStorage.setItem(key, JSON.stringify(Array.from(values)));
    }
  } catch {
    // ignore quota errors
  }
}

export interface UseTurnCollapseResult {
  collapsed: ReadonlySet<string>;
  isCollapsed: (turnId: string) => boolean;
  toggle: (turnId: string) => void;
  collapseAll: (turnIds: readonly string[]) => void;
  expandAll: () => void;
}

export function useTurnCollapse(conversationId: string | null | undefined): UseTurnCollapseResult {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => readSet(conversationId));

  // Reset when the active conversation changes.
  useEffect(() => {
    setCollapsed(readSet(conversationId));
  }, [conversationId]);

  // Persist whenever the set mutates.
  useEffect(() => {
    writeSet(conversationId, collapsed);
  }, [conversationId, collapsed]);

  const isCollapsed = useCallback((turnId: string) => collapsed.has(turnId), [collapsed]);

  const toggle = useCallback((turnId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(turnId)) {
        next.delete(turnId);
      } else {
        next.add(turnId);
      }
      return next;
    });
  }, []);

  const collapseAll = useCallback((turnIds: readonly string[]) => {
    setCollapsed(new Set(turnIds));
  }, []);

  const expandAll = useCallback(() => {
    setCollapsed(new Set());
  }, []);

  return useMemo(
    () => ({ collapsed, isCollapsed, toggle, collapseAll, expandAll }),
    [collapsed, isCollapsed, toggle, collapseAll, expandAll]
  );
}
