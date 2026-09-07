import { useCallback, useEffect, useState } from 'react';

import { cronAPI } from '../services/cronService';

import type { CronCapabilities } from '../services/cronService';

export function useCronCapabilities(projectId: string | undefined) {
  const [result, setResult] = useState<{
    projectId: string;
    capabilities: CronCapabilities | null;
    error: boolean;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    void cronAPI.capabilities(projectId).then(
      (capabilities) => {
        if (active) setResult({ projectId, capabilities, error: false });
      },
      () => {
        if (active) setResult({ projectId, capabilities: null, error: true });
      }
    );
    return () => {
      active = false;
    };
  }, [projectId, attempt]);

  const retry = useCallback(() => {
    setResult(null);
    setAttempt((value) => value + 1);
  }, []);
  const current = result?.projectId === projectId ? result : null;
  return {
    capabilities: current?.capabilities ?? null,
    error: current?.error ?? false,
    loading: Boolean(projectId) && current === null,
    retry,
  };
}
