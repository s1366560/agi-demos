import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { ProjectWorkItem } from '../../types';
import type {
  ActivityReadEntry as AuthorityReadEntry,
  ActivityAuthorityScope,
  CloudAgentAuthorityScope,
  DesktopAgentAuthorityAdapter,
  DesktopActivityAuthorityClient,
} from '../agent-authority/agentAuthorityTypes';
import {
  buildActivityInboxEntries,
  groupActivityEntries,
  type ActivityInboxEntry,
  type ActivityInboxGroup,
} from './activityInboxModel';
import {
  activityEntryIsRead,
  countUnreadActivityEntries,
  type ActivityReadState,
} from './activityReadState';

export type UseActivityInboxOptions = {
  items: ProjectWorkItem[];
  // Kept until App.tsx injects the authority adapter; it is never storage authority.
  scopeKey: string;
  authorityAdapter?: DesktopAgentAuthorityAdapter;
  authorityScope?: CloudAgentAuthorityScope;
};

export type ActivityInboxController = {
  entries: ActivityInboxEntry[];
  groups: ActivityInboxGroup[];
  unreadCount: number;
  availability: 'available' | 'degraded' | 'unavailable';
  reasonCode: string | null;
  isEntryRead: (entry: ActivityInboxEntry) => boolean;
  markRead: (entryId: string) => void;
  markAllRead: () => void;
  markConversationRead: (conversationId: string) => void;
};

export function activityAuthorityEntriesToReadState(
  entries: readonly AuthorityReadEntry[],
): ActivityReadState {
  return entries.reduce<ActivityReadState>((state, entry) => {
    const readAtMs = Date.parse(entry.read_at);
    if (!Number.isFinite(readAtMs)) return state;
    return { ...state, [entry.entry_id]: readAtMs };
  }, {});
}

export function activityEntriesToAuthorityReceipts(
  entries: readonly ActivityInboxEntry[],
  readAtMs: number,
): AuthorityReadEntry[] {
  const readAt = new Date(readAtMs).toISOString();
  return entries
    .map((entry) => ({
      entry_id: entry.id,
      entry_revision: entry.item.revision ?? 0,
      read_at: readAt,
    }))
    .sort((left, right) => left.entry_id.localeCompare(right.entry_id));
}

export function resolveActivityAuthorityBinding(
  authorityAdapter: DesktopAgentAuthorityAdapter | undefined,
  cloudScope: CloudAgentAuthorityScope | undefined,
): Readonly<{
  client: DesktopActivityAuthorityClient | null;
  scope: ActivityAuthorityScope | undefined;
}> {
  return {
    client: authorityAdapter?.activityClient ?? null,
    scope:
      authorityAdapter?.authority === 'local'
        ? authorityAdapter.activityScope
        : cloudScope,
  };
}

export function useActivityInbox({
  items,
  scopeKey,
  authorityAdapter,
  authorityScope,
}: UseActivityInboxOptions): ActivityInboxController {
  const [readState, setReadState] = useState<ActivityReadState>({});
  const [availability, setAvailability] = useState<
    ActivityInboxController['availability']
  >(authorityAdapter?.availability ?? 'unavailable');
  const [reasonCode, setReasonCode] = useState<string | null>(
    authorityAdapter?.reasonCode ??
      'activity_authority_integration_unavailable',
  );
  const authorityRevisionRef = useRef(0);
  const authorityEntriesRef = useRef<AuthorityReadEntry[]>([]);
  const authorityReadyRef = useRef(false);
  const pendingAuthorityEntriesRef = useRef<AuthorityReadEntry[]>([]);
  const authorityScopeGenerationRef = useRef(0);
  const authorityWriteChainRef = useRef<Promise<void>>(Promise.resolve());

  const entries = useMemo(() => buildActivityInboxEntries(items), [items]);
  const { client: activityClient, scope: effectiveAuthorityScope } =
    resolveActivityAuthorityBinding(authorityAdapter, authorityScope);

  const writeAuthorityEntries = useCallback(
    (incoming: readonly AuthorityReadEntry[]) => {
      if (!activityClient || !effectiveAuthorityScope || incoming.length === 0)
        return;
      const scopeGeneration = authorityScopeGenerationRef.current;
      authorityWriteChainRef.current = authorityWriteChainRef.current.then(
        async () => {
          if (scopeGeneration !== authorityScopeGenerationRef.current) return;
          const previousEntries = authorityEntriesRef.current;
          const receipts = mergeAuthorityReadEntries(previousEntries, incoming);
          authorityEntriesRef.current = receipts;
          setReadState(activityAuthorityEntriesToReadState(receipts));
          try {
            const result = await activityClient.putActivityReadState(
              effectiveAuthorityScope,
              {
                expected_authority_revision: authorityRevisionRef.current,
                entries: receipts,
              },
            );
            if (scopeGeneration !== authorityScopeGenerationRef.current) return;
            if (result.kind === 'queued_offline') {
              authorityRevisionRef.current = result.expectedAuthorityRevision;
              authorityEntriesRef.current = [...result.entries];
              setAvailability('degraded');
              setReasonCode(result.reasonCode);
              return;
            }
            authorityRevisionRef.current = result.state.authority_revision;
            authorityEntriesRef.current = [...result.state.entries];
            setReadState(
              activityAuthorityEntriesToReadState(result.state.entries),
            );
            setAvailability('available');
            setReasonCode(null);
          } catch {
            if (scopeGeneration !== authorityScopeGenerationRef.current) return;
            authorityEntriesRef.current = previousEntries;
            setReadState(activityAuthorityEntriesToReadState(previousEntries));
            setAvailability('degraded');
            setReasonCode(
              activityAuthorityReasonCode(authorityAdapter, 'update_failed'),
            );
            try {
              const state =
                await activityClient.getActivityReadState(
                  effectiveAuthorityScope,
                );
              if (scopeGeneration !== authorityScopeGenerationRef.current)
                return;
              authorityRevisionRef.current = state.authority_revision;
              authorityEntriesRef.current = [...state.entries];
              setReadState(activityAuthorityEntriesToReadState(state.entries));
            } catch {
              // Keep the last verified state; only offline retry receipts may remain optimistic.
            }
          }
        },
      );
    },
    [activityClient, authorityAdapter, effectiveAuthorityScope],
  );

  useEffect(() => {
    const controller = new AbortController();
    authorityScopeGenerationRef.current += 1;
    authorityRevisionRef.current = 0;
    authorityEntriesRef.current = [];
    authorityReadyRef.current = false;
    pendingAuthorityEntriesRef.current = [];
    authorityWriteChainRef.current = Promise.resolve();
    setReadState({});

    if (!activityClient || !effectiveAuthorityScope) {
      setAvailability('unavailable');
      setReasonCode(
        authorityAdapter?.reasonCode ??
          'activity_authority_integration_unavailable',
      );
      return () => controller.abort();
    }

    setAvailability('available');
    setReasonCode(null);
    void activityClient
      .flushPendingActivityReadState(effectiveAuthorityScope, {
        signal: controller.signal,
      })
      .then((result) => {
        if (controller.signal.aborted) return;
        if (result.kind === 'queued_offline') {
          authorityRevisionRef.current = result.expectedAuthorityRevision;
          authorityEntriesRef.current = [...result.entries];
          setReadState(activityAuthorityEntriesToReadState(result.entries));
          authorityReadyRef.current = true;
          setAvailability('degraded');
          setReasonCode(result.reasonCode);
        } else {
          authorityRevisionRef.current = result.state.authority_revision;
          authorityEntriesRef.current = [...result.state.entries];
          setReadState(
            activityAuthorityEntriesToReadState(result.state.entries),
          );
          authorityReadyRef.current = true;
          setAvailability('available');
          setReasonCode(null);
        }
        const pending = pendingAuthorityEntriesRef.current;
        pendingAuthorityEntriesRef.current = [];
        writeAuthorityEntries(pending);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setAvailability('degraded');
        setReasonCode(
          activityAuthorityReasonCode(authorityAdapter, 'unavailable'),
        );
      });
    return () => controller.abort();
  }, [
    authorityAdapter,
    activityClient,
    effectiveAuthorityScope,
    scopeKey,
    writeAuthorityEntries,
  ]);

  const commitRead = useCallback(
    (selectedEntries: readonly ActivityInboxEntry[]) => {
      if (
        !activityClient ||
        !effectiveAuthorityScope ||
        selectedEntries.length === 0
      )
        return;
      const incoming = activityEntriesToAuthorityReceipts(
        selectedEntries,
        Date.now(),
      );
      if (!authorityReadyRef.current) {
        pendingAuthorityEntriesRef.current = mergeAuthorityReadEntries(
          pendingAuthorityEntriesRef.current,
          incoming,
        );
        setReadState(
          activityAuthorityEntriesToReadState(
            mergeAuthorityReadEntries(
              authorityEntriesRef.current,
              pendingAuthorityEntriesRef.current,
            ),
          ),
        );
        return;
      }
      writeAuthorityEntries(incoming);
    },
    [activityClient, effectiveAuthorityScope, writeAuthorityEntries],
  );

  const markRead = useCallback(
    (entryId: string) => {
      const entry = entries.find((candidate) => candidate.id === entryId);
      if (entry) commitRead([entry]);
    },
    [commitRead, entries],
  );

  const markAllRead = useCallback(
    () => commitRead(entries),
    [commitRead, entries],
  );

  const markConversationRead = useCallback(
    (conversationId: string) => {
      commitRead(
        entries.filter((entry) => entry.conversationId === conversationId),
      );
    },
    [commitRead, entries],
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
    availability,
    reasonCode,
    isEntryRead,
    markRead,
    markAllRead,
    markConversationRead,
  };
}

function activityAuthorityReasonCode(
  adapter: DesktopAgentAuthorityAdapter | undefined,
  reason: 'unavailable' | 'update_failed',
): string {
  return `${adapter?.authority === 'local' ? 'local' : 'cloud'}_activity_read_state_${reason}`;
}

function mergeAuthorityReadEntries(
  current: readonly AuthorityReadEntry[],
  incoming: readonly AuthorityReadEntry[],
): AuthorityReadEntry[] {
  const entries = new Map(current.map((entry) => [entry.entry_id, entry]));
  incoming.forEach((entry) => entries.set(entry.entry_id, entry));
  return [...entries.values()].sort((left, right) =>
    left.entry_id.localeCompare(right.entry_id),
  );
}
