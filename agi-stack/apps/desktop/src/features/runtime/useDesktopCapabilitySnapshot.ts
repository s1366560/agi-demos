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
      .then((nextSnapshot) => setSnapshot(nextSnapshot))
      .catch(() => {
        if (!controller.signal.aborted) setSnapshot(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [attempt, client, enabled]);

  return { loading, reload, snapshot };
}
