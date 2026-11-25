import { useCallback, useLayoutEffect, useRef } from 'react';
import type { MarketplaceTransport } from '../../../agi-stack/packages/plugin-marketplace-ui/src/client';
import type { SidebarSlot } from '../../../agi-stack/packages/plugin-slots/src/sidebar';
import { invokeSlot, type SlotOwner } from './sidebarSlots';

export function useSidebarSlot(
  tenant: string,
  project: string | null,
  owner: SlotOwner | undefined,
  transport: MarketplaceTransport
) {
  const scope = useRef<AbortController | null>(null);
  const call = useCallback(
    (slot: SidebarSlot, values: Record<string, unknown>, signal?: AbortSignal) => {
      const controller = scope.current;
      if (!controller || !project || controller.signal.aborted)
        throw new Error('page_scope_expired');
      return invokeSlot(
        transport,
        tenant,
        project,
        owner,
        slot,
        values,
        signal ? AbortSignal.any([controller.signal, signal]) : controller.signal
      );
    },
    [tenant, project, owner, transport]
  );
  const currentCall = useRef<typeof call | null>(null);
  useLayoutEffect(() => {
    const controller = new AbortController();
    currentCall.current = call;
    scope.current = controller;
    return () => {
      controller.abort();
      currentCall.current = null;
    };
  }, [call]);
  return useCallback(
    (...args: Parameters<typeof call>) => {
      if (currentCall.current !== call) throw new Error('page_scope_expired');
      return call(...args);
    },
    [call]
  );
}
