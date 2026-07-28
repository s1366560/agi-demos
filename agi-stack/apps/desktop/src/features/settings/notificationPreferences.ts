import { useCallback, useEffect, useRef, useState } from 'react';

export type NotificationDelivery = 'desktop_and_in_app' | 'desktop' | 'in_app';

export type NotificationPreferences = Readonly<{
  reviewAlerts: boolean;
  delivery: NotificationDelivery;
  quietHours: Readonly<{
    enabled: boolean;
    start: string;
    end: string;
  }>;
}>;

type NotificationPreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>;

type StoredNotificationPreferences = Readonly<{
  version: 1;
  reviewAlerts: boolean;
  delivery: NotificationDelivery;
  quietHours: NotificationPreferences['quietHours'];
}>;

export const NOTIFICATION_PREFERENCES_STORAGE_KEY =
  'agistack.desktop.notification-preferences:v1';

export const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferences = Object.freeze({
  reviewAlerts: true,
  delivery: 'desktop_and_in_app',
  quietHours: Object.freeze({
    enabled: false,
    start: '22:00',
    end: '08:00',
  }),
});

const DELIVERY_VALUES = new Set<NotificationDelivery>([
  'desktop_and_in_app',
  'desktop',
  'in_app',
]);
const TIME_VALUE_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

export function parseNotificationPreferences(raw: string | null): NotificationPreferences {
  if (!raw) return cloneNotificationPreferences(DEFAULT_NOTIFICATION_PREFERENCES);
  try {
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value) || value.version !== 1) {
      return cloneNotificationPreferences(DEFAULT_NOTIFICATION_PREFERENCES);
    }
    if (
      typeof value.reviewAlerts !== 'boolean' ||
      typeof value.delivery !== 'string' ||
      !DELIVERY_VALUES.has(value.delivery as NotificationDelivery) ||
      !isRecord(value.quietHours) ||
      typeof value.quietHours.enabled !== 'boolean' ||
      typeof value.quietHours.start !== 'string' ||
      !TIME_VALUE_PATTERN.test(value.quietHours.start) ||
      typeof value.quietHours.end !== 'string' ||
      !TIME_VALUE_PATTERN.test(value.quietHours.end)
    ) {
      return cloneNotificationPreferences(DEFAULT_NOTIFICATION_PREFERENCES);
    }
    return {
      reviewAlerts: value.reviewAlerts,
      delivery: value.delivery as NotificationDelivery,
      quietHours: {
        enabled: value.quietHours.enabled,
        start: value.quietHours.start,
        end: value.quietHours.end,
      },
    };
  } catch {
    return cloneNotificationPreferences(DEFAULT_NOTIFICATION_PREFERENCES);
  }
}

export function readNotificationPreferences(
  storage: NotificationPreferenceStorage | null = browserStorage(),
): NotificationPreferences {
  if (!storage) return cloneNotificationPreferences(DEFAULT_NOTIFICATION_PREFERENCES);
  try {
    return parseNotificationPreferences(storage.getItem(NOTIFICATION_PREFERENCES_STORAGE_KEY));
  } catch {
    return cloneNotificationPreferences(DEFAULT_NOTIFICATION_PREFERENCES);
  }
}

export function writeNotificationPreferences(
  preferences: NotificationPreferences,
  storage: NotificationPreferenceStorage | null = browserStorage(),
): void {
  if (!storage) return;
  const snapshot: StoredNotificationPreferences = {
    version: 1,
    ...cloneNotificationPreferences(preferences),
  };
  try {
    storage.setItem(NOTIFICATION_PREFERENCES_STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // The in-memory preference remains authoritative when storage is unavailable.
  }
}

export function useNotificationPreferences(): {
  preferences: NotificationPreferences;
  setPreferences: (
    update:
      | NotificationPreferences
      | ((current: NotificationPreferences) => NotificationPreferences),
  ) => void;
} {
  const [preferences, setPreferencesState] = useState<NotificationPreferences>(() =>
    readNotificationPreferences(),
  );
  const preferencesRef = useRef(preferences);

  const setPreferences = useCallback(
    (
      update:
        | NotificationPreferences
        | ((current: NotificationPreferences) => NotificationPreferences),
    ) => {
      const nextPreferences =
        typeof update === 'function' ? update(preferencesRef.current) : update;
      const snapshot = cloneNotificationPreferences(nextPreferences);
      preferencesRef.current = snapshot;
      setPreferencesState(snapshot);
      writeNotificationPreferences(snapshot);
    },
    [],
  );

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const handleStorage = (event: StorageEvent) => {
      if (event.key === NOTIFICATION_PREFERENCES_STORAGE_KEY) {
        const snapshot = parseNotificationPreferences(event.newValue);
        preferencesRef.current = snapshot;
        setPreferencesState(snapshot);
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  return { preferences, setPreferences };
}

function cloneNotificationPreferences(
  preferences: NotificationPreferences,
): NotificationPreferences {
  return {
    reviewAlerts: preferences.reviewAlerts,
    delivery: preferences.delivery,
    quietHours: { ...preferences.quietHours },
  };
}

function browserStorage(): NotificationPreferenceStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
