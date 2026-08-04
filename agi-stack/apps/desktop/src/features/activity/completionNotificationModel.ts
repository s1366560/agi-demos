import type { ActivityCategory, ActivityInboxEntry } from './activityInboxModel';
import type {
  CompletionNotificationMode,
  NotificationDelivery,
  NotificationPreferences,
} from '../settings/notificationPreferences';

// Only these inbox categories justify an OS interruption; `attention`
// (failures) stays in-app for now.
export type CompletionNotificationKind = Extract<
  ActivityCategory,
  'needs_input' | 'ready_for_review'
>;

export type CompletionNotificationTrigger = Readonly<{
  entryId: string;
  conversationId: string;
  title: string;
  kind: CompletionNotificationKind;
}>;

export type CompletionNotificationSnapshot = ReadonlyMap<string, ActivityCategory>;

export type CompletionNotificationGateOptions = Readonly<{
  mode: CompletionNotificationMode;
  delivery: NotificationDelivery;
  reviewAlerts: boolean;
  quietHours: NotificationPreferences['quietHours'];
  windowFocused: boolean;
  now?: Date;
}>;

type TransitionEntry = Pick<
  ActivityInboxEntry,
  'id' | 'conversationId' | 'title' | 'category'
>;

// Diff two inbox projections and surface only entries that moved INTO a
// notifiable category. A `null` previous snapshot marks the initial sync:
// everything already in a notifiable state on load is baseline, not a
// transition, so first paint never storms the notification center.
export function detectCompletionTransitions(
  previous: CompletionNotificationSnapshot | null,
  entries: readonly TransitionEntry[],
): {
  triggers: CompletionNotificationTrigger[];
  snapshot: CompletionNotificationSnapshot;
} {
  const snapshot = new Map<string, ActivityCategory>();
  for (const entry of entries) snapshot.set(entry.id, entry.category);
  if (previous === null) return { triggers: [], snapshot };
  const triggers: CompletionNotificationTrigger[] = [];
  for (const entry of entries) {
    if (entry.category !== 'needs_input' && entry.category !== 'ready_for_review') continue;
    if (previous.get(entry.id) === entry.category) continue;
    triggers.push({
      entryId: entry.id,
      conversationId: entry.conversationId,
      title: entry.title,
      kind: entry.category,
    });
  }
  return { triggers, snapshot };
}

export function completionNotificationAllowed(
  options: CompletionNotificationGateOptions,
): boolean {
  if (!options.reviewAlerts) return false;
  if (options.delivery === 'in_app') return false;
  if (options.mode === 'off') return false;
  if (options.mode === 'window_not_focused' && options.windowFocused) return false;
  return !quietHoursActive(options.quietHours, options.now ?? new Date());
}

// Quiet hours use local wall-clock minutes and support overnight ranges
// (start > end wraps midnight). A zero-length range (start === end) is
// treated as disabled to avoid a 24h blackout from a misconfigured pair.
export function quietHoursActive(
  quietHours: NotificationPreferences['quietHours'],
  now: Date,
): boolean {
  if (!quietHours.enabled) return false;
  const start = minutesOfDay(quietHours.start);
  const end = minutesOfDay(quietHours.end);
  if (start === null || end === null || start === end) return false;
  const current = now.getHours() * 60 + now.getMinutes();
  if (start < end) return current >= start && current < end;
  return current >= start || current < end;
}

function minutesOfDay(value: string): number | null {
  const match = /^(?:[01]\d|2[0-3]):([0-5]\d)$/.exec(value);
  if (!match) return null;
  return Number(value.slice(0, 2)) * 60 + Number(match[1]);
}
