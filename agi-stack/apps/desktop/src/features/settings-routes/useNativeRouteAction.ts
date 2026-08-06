import { useCallback, useState } from 'react';

import { nativeRouteFailure } from './nativeRouteHttpClient';

export type NativeRouteActionResult<T> =
  | Readonly<{ ok: true; value: T }>
  | Readonly<{ ok: false; reasonCode: string }>;

export function useNativeRouteAction(fallbackReasonCode: string) {
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [reasonCode, setReasonCode] = useState<string | null>(null);

  const run = useCallback(
    async <T>(action: string, operation: () => Promise<T>): Promise<NativeRouteActionResult<T>> => {
      setBusyAction(action);
      setReasonCode(null);
      try {
        return Object.freeze({ ok: true, value: await operation() });
      } catch (error) {
        const failure = nativeRouteFailure(error, fallbackReasonCode);
        setReasonCode(failure.reasonCode);
        return Object.freeze({ ok: false, reasonCode: failure.reasonCode });
      } finally {
        setBusyAction(null);
      }
    },
    [fallbackReasonCode],
  );

  return Object.freeze({ busyAction, reasonCode, run });
}
