import { useEffect, useRef } from 'react';

import { useI18n } from '../../i18n';
import { useNotificationPreferences } from '../settings/notificationPreferences';
import type { ActivityInboxEntry } from './activityInboxModel';
import {
  completionNotificationAllowed,
  detectCompletionTransitions,
  type CompletionNotificationSnapshot,
  type CompletionNotificationTrigger,
} from './completionNotificationModel';

export type UseCompletionNotificationsOptions = {
  entries: readonly ActivityInboxEntry[];
  // Tenant/project scope; a scope change re-baselines the transition tracker
  // so the freshly loaded inbox never fires as a batch of "new" transitions.
  scopeKey: string;
  // False while the first workspace sync is in flight; entries observed during
  // that window are absorbed as baseline instead of notified.
  hydrated: boolean;
  // Invoked when the user clicks a delivered OS notification; the host
  // navigates to the originating conversation.
  onOpenEntry: (entry: ActivityInboxEntry) => void;
};

// Watches the Activity inbox projection for transitions INTO needs_input /
// ready_for_review and raises an OS notification for each, subject to the
// user's notification preferences and the current window focus.
export function useCompletionNotifications({
  entries,
  scopeKey,
  hydrated,
  onOpenEntry,
}: UseCompletionNotificationsOptions): void {
  const { t } = useI18n();
  const { preferences } = useNotificationPreferences();
  const snapshotRef = useRef<CompletionNotificationSnapshot | null>(null);
  const scopeRef = useRef(scopeKey);
  const entriesRef = useRef(entries);
  const onOpenEntryRef = useRef(onOpenEntry);
  entriesRef.current = entries;
  onOpenEntryRef.current = onOpenEntry;

  useEffect(() => {
    if (scopeRef.current !== scopeKey) {
      scopeRef.current = scopeKey;
      snapshotRef.current = null;
    }
    if (!hydrated) {
      snapshotRef.current = detectCompletionTransitions(null, entries).snapshot;
      return;
    }
    const { triggers, snapshot } = detectCompletionTransitions(snapshotRef.current, entries);
    snapshotRef.current = snapshot;
    if (triggers.length === 0) return;
    if (typeof window === 'undefined' || typeof Notification === 'undefined') return;
    const windowFocused = typeof document === 'undefined' ? true : document.hasFocus();
    if (
      !completionNotificationAllowed({
        mode: preferences.completionMode,
        delivery: preferences.delivery,
        reviewAlerts: preferences.reviewAlerts,
        quietHours: preferences.quietHours,
        windowFocused,
      })
    ) {
      return;
    }
    for (const trigger of triggers) {
      void deliverCompletionNotification(
        trigger,
        {
          needs_input: t('notifications.needsInput'),
          ready_for_review: t('notifications.readyForReview'),
        }[trigger.kind],
        entriesRef,
        onOpenEntryRef,
      );
    }
  }, [entries, hydrated, preferences, scopeKey, t]);
}

async function deliverCompletionNotification(
  trigger: CompletionNotificationTrigger,
  kindLabel: string,
  entriesRef: { current: readonly ActivityInboxEntry[] },
  onOpenEntryRef: { current: (entry: ActivityInboxEntry) => void },
): Promise<void> {
  try {
    if (Notification.permission === 'default') {
      await Notification.requestPermission();
    }
  } catch {
    return;
  }
  if (Notification.permission !== 'granted') return;
  // Title carries the conversation title; body carries the transition kind so
  // the notification alone identifies which session needs attention. `tag`
  // collapses repeat transitions of the same inbox entry.
  const notification = new Notification(trigger.title, {
    body: kindLabel,
    tag: trigger.entryId,
  });
  notification.onclick = () => {
    void window.__MEMSTACK_DESKTOP__?.focusMainWindow?.().catch(() => {});
    window.focus();
    const entry = entriesRef.current.find((candidate) => candidate.id === trigger.entryId);
    if (entry) onOpenEntryRef.current(entry);
  };
}
