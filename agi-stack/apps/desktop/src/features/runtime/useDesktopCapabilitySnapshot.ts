import { useCallback, useEffect, useState } from 'react';

import type { DesktopCapabilitySnapshot } from './capabilitySnapshot';
import type { DesktopWorkbenchCapabilityClient } from './workbenchCapabilityClient';

export type DesktopCapabilityLoadState = {
  loading: boolean;
  reload: () => void;
  snapshot: DesktopCapabilitySnapshot | null;
};

export function useDesktopCapabilitySnapshot(
  client: DesktopWorkbenchCapabilityClient,
  enabled: boolean,
): DesktopCapabilityLoadState {
  const [snapshot, setSnapshot] = useState<DesktopCapabilitySnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt((current) => current + 1), []);

  useEffect(() => {
    setSnapshot(null);
    if (!enabled) {
      setLoading(false);
      return undefined;
    }

    const controller = new AbortController();
    setLoading(true);
    void client
      .loadSnapshot(controller.signal)
      .then((nextSnapshot) => {
        if (!controller.signal.aborted) setSnapshot(nextSnapshot);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.warn('[desktop-capability-snapshot]', capabilitySnapshotFailureCode(error));
          setSnapshot(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [attempt, client, enabled]);

  return { loading, reload, snapshot };
}

function capabilitySnapshotFailureCode(error: unknown): string {
  if (typeof error !== 'object' || error === null) return 'snapshot_load_failed';
  for (const key of ['reasonCode', 'code']) {
    const value = Reflect.get(error, key);
    if (typeof value === 'string' && /^[a-z][a-z0-9_:-]{0,255}$/.test(value)) return value;
  }
  return 'snapshot_load_failed';
}
