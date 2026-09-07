import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { ProjectWorkItem } from '../../types';
import type {
  ActivityReadEntry as AuthorityReadEntry,
  ActivityAuthorityScope,
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
  scopeKey: string;
  activityClientV2: DesktopActivityAuthorityClient;
  authorityScope: ActivityAuthorityScope | null;
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

type ActivityLifetime = {
  context: Readonly<{
    client: DesktopActivityAuthorityClient;
    scope: ActivityAuthorityScope | null;
    scopeKey: string;
  }>;
  controller: AbortController;
  revision: number;
  entries: AuthorityReadEntry[];
  pending: AuthorityReadEntry[];
  ready: boolean;
  writes: Promise<void>;
};

export function useActivityInbox({
  items,
  scopeKey,
  activityClientV2,
  authorityScope,
}: UseActivityInboxOptions): ActivityInboxController {
  const context = useMemo(
    () =>
      Object.freeze({
        client: activityClientV2,
        scope: authorityScope ? Object.freeze({ ...authorityScope }) : null,
        scopeKey,
      }),
    [
      activityClientV2,
      scopeKey,
      authorityScope?.authority,
      authorityScope?.principalId,
      authorityScope?.tenantId,
      authorityScope?.projectId,
    ],
  );
  const contextRef = useRef(context);
  contextRef.current = context;
  const lifetimeRef = useRef<ActivityLifetime | null>(null);
  const [readState, setReadState] = useState<ActivityReadState>({});
  const [availability, setAvailability] =
    useState<ActivityInboxController['availability']>('unavailable');
  const [reasonCode, setReasonCode] = useState<string | null>(
    'activity_authority_integration_unavailable',
  );
  const entries = useMemo(() => buildActivityInboxEntries(items), [items]);
  const isCurrent = useCallback(
    (lifetime: ActivityLifetime) =>
      lifetimeRef.current === lifetime &&
      contextRef.current === lifetime.context &&
      !lifetime.controller.signal.aborted,
    [],
  );

  const writeAuthorityEntries = useCallback(
    (incoming: readonly AuthorityReadEntry[], lifetime: ActivityLifetime) => {
      if (
        !isCurrent(lifetime) ||
        lifetime.context !== context ||
        !context.scope ||
        incoming.length === 0
      )
        return;
      const scope = context.scope;
      lifetime.writes = lifetime.writes.then(async () => {
        if (!isCurrent(lifetime)) return;
        const previousEntries = lifetime.entries;
        const receipts = mergeAuthorityReadEntries(previousEntries, incoming);
        lifetime.entries = receipts;
        setReadState(activityAuthorityEntriesToReadState(receipts));
        try {
          const result = await context.client.putActivityReadState(
            scope,
            {
              expected_authority_revision: lifetime.revision,
              entries: receipts,
            },
            { signal: lifetime.controller.signal },
          );
          if (!isCurrent(lifetime)) return;
          if (result.kind === 'queued_offline') {
            lifetime.revision = result.expectedAuthorityRevision;
            lifetime.entries = [...result.entries];
            setReadState(activityAuthorityEntriesToReadState(result.entries));
            setAvailability('degraded');
            setReasonCode(result.reasonCode);
          } else {
            lifetime.revision = result.state.authority_revision;
            lifetime.entries = [...result.state.entries];
            setReadState(activityAuthorityEntriesToReadState(result.state.entries));
            setAvailability('available');
            setReasonCode(null);
          }
        } catch {
          if (!isCurrent(lifetime)) return;
          lifetime.entries = previousEntries;
          setReadState(activityAuthorityEntriesToReadState(previousEntries));
          setAvailability('degraded');
          setReasonCode(activityAuthorityReasonCode(scope, 'update_failed'));
          try {
            const state = await context.client.getActivityReadState(scope, {
              signal: lifetime.controller.signal,
            });
            if (!isCurrent(lifetime)) return;
            lifetime.revision = state.authority_revision;
            lifetime.entries = [...state.entries];
            setReadState(activityAuthorityEntriesToReadState(state.entries));
          } catch {
            // Keep the last verified state; only offline retry receipts may remain optimistic.
          }
        }
      });
    },
    [context, isCurrent],
  );

  useEffect(() => {
    const lifetime: ActivityLifetime = {
      context,
      controller: new AbortController(),
      revision: 0,
      entries: [],
      pending: [],
      ready: false,
      writes: Promise.resolve(),
    };
    lifetimeRef.current = lifetime;
    setReadState({});
    const cleanup = () => {
      lifetime.controller.abort();
      lifetime.pending = [];
    };
    if (!context.scope) {
      setAvailability('unavailable');
      setReasonCode('activity_authority_integration_unavailable');
      return cleanup;
    }
    const scope = context.scope;
    setAvailability('available');
    setReasonCode(null);
    void context.client
      .flushPendingActivityReadState(scope, { signal: lifetime.controller.signal })
      .then((result) => {
        if (!isCurrent(lifetime)) return;
        if (result.kind === 'queued_offline') {
          lifetime.revision = result.expectedAuthorityRevision;
          lifetime.entries = [...result.entries];
          setReadState(activityAuthorityEntriesToReadState(result.entries));
          setAvailability('degraded');
          setReasonCode(result.reasonCode);
        } else {
          lifetime.revision = result.state.authority_revision;
          lifetime.entries = [...result.state.entries];
          setReadState(activityAuthorityEntriesToReadState(result.state.entries));
          setAvailability('available');
          setReasonCode(null);
        }
        lifetime.ready = true;
        const pending = lifetime.pending;
        lifetime.pending = [];
        writeAuthorityEntries(pending, lifetime);
      })
      .catch(() => {
        if (!isCurrent(lifetime)) return;
        setAvailability('degraded');
        setReasonCode(activityAuthorityReasonCode(scope, 'unavailable'));
      });
    return cleanup;
  }, [context, isCurrent, writeAuthorityEntries]);

  const commitRead = useCallback(
    (selectedEntries: readonly ActivityInboxEntry[]) => {
      const lifetime = lifetimeRef.current;
      if (
        !lifetime ||
        lifetime.context !== context ||
        !isCurrent(lifetime) ||
        !context.scope ||
        selectedEntries.length === 0
      )
        return;
      const incoming = activityEntriesToAuthorityReceipts(selectedEntries, Date.now());
      if (!lifetime.ready) {
        lifetime.pending = mergeAuthorityReadEntries(lifetime.pending, incoming);
        setReadState(
          activityAuthorityEntriesToReadState(
            mergeAuthorityReadEntries(lifetime.entries, lifetime.pending),
          ),
        );
        return;
      }
      writeAuthorityEntries(incoming, lifetime);
    },
    [context, isCurrent, writeAuthorityEntries],
  );

  const markRead = useCallback(
    (entryId: string) => {
      const entry = entries.find((candidate) => candidate.id === entryId);
      if (entry) commitRead([entry]);
    },
    [commitRead, entries],
  );

  const markAllRead = useCallback(() => commitRead(entries), [commitRead, entries]);

  const markConversationRead = useCallback(
    (conversationId: string) => {
      commitRead(entries.filter((entry) => entry.conversationId === conversationId));
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
  scope: ActivityAuthorityScope,
  reason: 'unavailable' | 'update_failed',
): string {
  return `${scope.authority === 'local' ? 'local' : 'cloud'}_activity_read_state_${reason}`;
}

function mergeAuthorityReadEntries(
  current: readonly AuthorityReadEntry[],
  incoming: readonly AuthorityReadEntry[],
): AuthorityReadEntry[] {
  const entries = new Map(current.map((entry) => [entry.entry_id, entry]));
  incoming.forEach((entry) => entries.set(entry.entry_id, entry));
  return [...entries.values()].sort((left, right) => left.entry_id.localeCompare(right.entry_id));
}
