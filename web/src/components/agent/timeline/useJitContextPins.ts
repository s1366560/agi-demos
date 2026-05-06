/**
 * useJitContextPins - per-conversation persistent pins for JIT context hits.
 *
 * Storage key: `memstack:jit-pins:<conversationId>` => string[] of memory hit
 * keys (`<eventId>:<index>`).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

const STORAGE_PREFIX = 'memstack:jit-pins:';

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
    // ignore
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

export interface UseJitContextPinsResult {
  pinned: ReadonlySet<string>;
  isPinned: (key: string) => boolean;
  toggle: (key: string) => void;
}

export function useJitContextPins(
  conversationId: string | null | undefined
): UseJitContextPinsResult {
  const [pinned, setPinned] = useState<Set<string>>(() => readSet(conversationId));

  useEffect(() => {
    setPinned(readSet(conversationId));
  }, [conversationId]);

  useEffect(() => {
    writeSet(conversationId, pinned);
  }, [conversationId, pinned]);

  const isPinned = useCallback((key: string) => pinned.has(key), [pinned]);

  const toggle = useCallback((key: string) => {
    setPinned((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  return useMemo(() => ({ pinned, isPinned, toggle }), [pinned, isPinned, toggle]);
}
