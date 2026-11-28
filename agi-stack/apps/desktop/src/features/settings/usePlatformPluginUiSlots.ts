import { useMemo } from 'react';

import {
  selectDesktopUiSlotsV2,
  useDesktopRendererAuthorityV2,
} from '../../plugins/desktopRendererAuthorityStateV2';

export function usePlatformPluginUiSlots({ active }: { active: boolean }) {
  const authority = useDesktopRendererAuthorityV2();
  const slots = useMemo(
    () => (active ? selectDesktopUiSlotsV2(authority) : []),
    [active, authority],
  );
  return {
    slots,
    error:
      active && authority.status === 'unavailable'
        ? authority.error instanceof Error
          ? authority.error.message
          : String(authority.error)
        : null,
    loading: active && authority.status === 'loading',
  };
}
