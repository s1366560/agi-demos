import { useEffect, useMemo, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  UiSlotDefinition,
  UiSlotRegistry,
  UiSlotRuntime,
} from '../../plugins/uiSlotRuntime';

const BUILTIN_UI_SLOT_DEFINITIONS: readonly UiSlotDefinition[] = Object.freeze([
  {
    pluginId: 'builtin-ui',
    slot: 'settings_page',
    id: 'plugin-settings',
    moduleRef: 'builtin:plugin-settings',
    permission: 'ui.settings.plugins',
    sandbox: true,
  },
  {
    pluginId: 'builtin-ui',
    slot: 'tool_result_renderer',
    id: 'structured-tool-result',
    moduleRef: 'builtin:structured-tool-result',
    permission: 'ui.render',
    sandbox: true,
  },
]);

export function usePlatformPluginUiSlots({
  active,
  config,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
}) {
  const runtime = useMemo(() => new UiSlotRuntime(new UiSlotRegistry()), []);
  const runtimeRef = useRef(runtime);
  const [slots, setSlots] = useState<readonly ReturnType<UiSlotRegistry['list']>[number][]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    runtimeRef.current = runtime;
  }, [runtime]);

  useEffect(() => {
    if (!active) {
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    new DesktopApiClient(config)
      .getPlatformPluginSnapshot(controller.signal)
      .then((snapshot) => {
        if (controller.signal.aborted) return;
        setSlots(runtimeRef.current.reconcile(snapshot, BUILTIN_UI_SLOT_DEFINITIONS).slots);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setSlots(runtimeRef.current.reconcile({ plugins: [] }, BUILTIN_UI_SLOT_DEFINITIONS).slots);
        setError(caught instanceof Error ? caught.message : String(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [active, config]);

  useEffect(() => () => runtimeRef.current.dispose(), []);

  return { slots, error, loading };
}
