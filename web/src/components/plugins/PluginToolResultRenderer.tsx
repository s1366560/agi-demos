import {
  createElement,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import {
  loadReplMediaV2,
  validateReplOutputPresentationV2,
  type ToolResultMediaV2,
  type ToolResultPresentationV2,
} from '@agistack/plugin-slots';
import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
} from '@/plugins/webOperationAdmissionV2';
import { readConversationToolMediaV2 } from '@/services/conversationToolMediaClientV2';

import { useAgentV3Store } from '@/stores/agentV3';
import { useProjectStore } from '@/stores/project';

import {
  useWebToolResultSlotV2,
  useWebUiSlotAuthorityV2,
} from '@/routes/v2/webUiSlotAuthorityStateV2';

import { PluginSlotHost } from './PluginSlotHost';

import type { SlotContextV2 } from '@agistack/plugin-slots';

export interface PluginToolResultRendererProps {
  readonly toolName: string;
  readonly result: string;
  readonly display?: { readonly kind?: string; readonly entries?: unknown } | undefined;
  readonly fallback: ReactNode;
}

export function PluginToolResultRenderer({
  toolName,
  result,
  display,
  fallback,
}: PluginToolResultRendererProps) {
  const { t } = useTranslation();
  const slot = useWebToolResultSlotV2(toolName);
  const authority = useWebUiSlotAuthorityV2();
  const project = useProjectStore((state) => state.currentProject);
  const tenantId = project?.tenant_id;
  const projectId = project?.id;
  const conversationId = useAgentV3Store((state) => state.activeConversationId);
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );
  const owner = useMemo(
    () =>
      tenantId !== undefined && projectId !== undefined && conversationId
        ? Object.freeze({
            tenantId,
            projectId,
            conversationId,
            operationOwner: availability.owner,
          })
        : null,
    [tenantId, projectId, conversationId, availability.owner]
  );
  const presentationKey = JSON.stringify(
    validateReplOutputPresentationV2(display) ?? { kind: 'text', text: result }
  );
  const presentation = useMemo<ToolResultPresentationV2>(
    () => JSON.parse(presentationKey),
    [presentationKey]
  );
  const [loaded, setLoaded] = useState<Readonly<{
    owner: typeof owner;
    presentation: ToolResultPresentationV2;
    media: readonly ToolResultMediaV2[];
  }> | null>(null);
  useEffect(() => {
    // Discard prior authority-scoped media as soon as the loading effect is replaced.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- prevent stale media on reactivation
    setLoaded(null);
    if (!slot || !owner || !availability.available || presentation.kind !== 'repl_output') return;
    const controller = new AbortController();
    void loadReplMediaV2(
      presentation,
      (reference, signal) => readConversationToolMediaV2(owner, reference, signal),
      controller.signal
    )
      .then((media) => {
        if (!controller.signal.aborted) setLoaded({ owner, presentation, media });
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [slot, owner, availability.available, presentation]);
  const context = useMemo<SlotContextV2<'tool_result_renderer'>>(
    () => ({
      kind: 'tool-result',
      toolName,
      status: 'complete',
      presentation,
      media:
        loaded?.owner === owner && loaded.presentation === presentation ? loaded.media : undefined,
      mediaLabel: t('components.messageStream.output', { defaultValue: 'Output' }),
      mediaLoadingLabel: t('common.loading'),
      mediaUnavailableLabel: t('plugins.rendererUnavailable'),
      conversationId,
      ...(owner ? { tenantId: owner.tenantId, projectId: owner.projectId } : {}),
    }),
    [toolName, presentation, loaded, owner, conversationId, t]
  );
  if (!slot) return <>{fallback}</>;
  const renderer = authority.renderers?.resolve(slot);
  const key = `${authority.generationId ?? 'standalone'}/${slot.pluginId}/${slot.id}`;
  if (renderer) return createElement(renderer, { key, slot, context });
  return (
    <PluginSlotHost
      key={key}
      slot={slot}
      generationId={authority.generationId}
      initPayload={context}
      fallback={fallback}
    />
  );
}
