import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  decodeSlotMessage,
  encodeSlotMessage,
  isGuestMessageForSlot,
} from '@agistack/plugin-slots';

import { useI18n } from '../../i18n';
import { useOptionalDesktopRendererGenerationV2 } from '../../plugins/desktopRendererGenerationContextV2';
import type { DesktopToolResultRendererModuleV2 } from '../../plugins/desktopToolResultRendererModuleV2';
import type { AuthorizedUiSlotDefinitionV2 } from '../../plugins/uiSlotRegistry';
import { usePlatformPluginUiSlots } from '../settings/usePlatformPluginUiSlots';
import type { ToolCallPresentationKind } from './chatTimelineModel';
import {
  createDesktopToolResultRendererPayloadV2,
  DesktopToolResultRendererBridgeV2,
  type DesktopToolResultRendererPayloadV2,
  type DesktopToolResultRendererProtocolV2,
  type DesktopToolResultRendererStatusV2,
} from './desktopToolResultRendererBridgeV2';

const TOOL_RESULT_RENDERER_PROTOCOL_V2: DesktopToolResultRendererProtocolV2 = Object.freeze({
  decode: decodeSlotMessage,
  encode: encodeSlotMessage,
  isGuestForSlot: isGuestMessageForSlot,
});

export interface PlatformPluginToolResultSlotsProps {
  readonly resultId: string;
  readonly toolName: string;
  readonly status: DesktopToolResultRendererStatusV2;
  readonly kind: ToolCallPresentationKind;
}

export function PlatformPluginToolResultSlots({
  resultId,
  toolName,
  status,
  kind,
}: PlatformPluginToolResultSlotsProps) {
  const { t } = useI18n();
  const generation = useOptionalDesktopRendererGenerationV2();
  const { slots, error, loading } = usePlatformPluginUiSlots({ active: true });
  const [hostError, setHostError] = useState<string | null>(null);
  const payload = useMemo(
    () =>
      createDesktopToolResultRendererPayloadV2({
        resultId,
        toolName,
        status,
        kind,
        resultLabel: t('chat.toolResult'),
        kindLabel: kind === 'tool' ? t('chat.toolResult') : t(`session.toolKind.${kind}`),
        statusLabel: t(`session.toolStatus.${status}`),
      }),
    [kind, resultId, status, t, toolName],
  );
  const visible = slots.filter((slot) => slot.slot === 'tool_result_renderer');
  if (generation === null || visible.length === 0) return null;

  return (
    <section
      className="platform-plugin-tool-result-slots"
      aria-live="polite"
      data-loading={loading || undefined}
      data-error={hostError ?? error ?? undefined}
    >
      {visible.map((slot) => {
        const module = generation.composition.resolveToolResultRendererModule(slot);
        if (module === null) return null;
        return (
          <DesktopToolResultRendererFrameV2
            key={`${slot.pluginId}:${slot.id}`}
            module={module}
            onError={setHostError}
            payload={payload}
            slot={slot}
          />
        );
      })}
    </section>
  );
}

function DesktopToolResultRendererFrameV2({
  module,
  onError,
  payload,
  slot,
}: Readonly<{
  module: DesktopToolResultRendererModuleV2;
  onError: (errorCode: string) => void;
  payload: DesktopToolResultRendererPayloadV2;
  slot: AuthorizedUiSlotDefinitionV2;
}>) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const bridgeRef = useRef<DesktopToolResultRendererBridgeV2 | null>(null);
  const frameLoadedRef = useRef(false);
  const payloadRef = useRef(payload);
  const [height, setHeight] = useState(40);
  payloadRef.current = payload;

  const handleFrameLoad = useCallback(() => {
    frameLoadedRef.current = true;
    bridgeRef.current?.activate();
  }, []);

  useEffect(() => {
    const frameWindow = iframeRef.current?.contentWindow;
    if (frameWindow === null || frameWindow === undefined) return;
    const bridge = new DesktopToolResultRendererBridgeV2({
      frameWindow,
      onError,
      onResize: setHeight,
      payload: payloadRef.current,
      protocol: TOOL_RESULT_RENDERER_PROTOCOL_V2,
      slotId: slot.id,
    });
    bridgeRef.current = bridge;
    if (frameLoadedRef.current) bridge.activate();
    const listener = (event: MessageEvent) => {
      bridge.handleMessage(event);
    };
    window.addEventListener('message', listener);
    return () => {
      window.removeEventListener('message', listener);
      bridge.dispose();
      if (bridgeRef.current === bridge) bridgeRef.current = null;
    };
  }, [module, onError, slot.id]);

  useEffect(() => {
    bridgeRef.current?.updatePayload(payload);
  }, [payload]);

  return (
    <iframe
      ref={iframeRef}
      className="platform-plugin-tool-result-frame"
      data-contract={slot.contract}
      data-module-ref={module.moduleRef}
      data-plugin-id={slot.pluginId}
      height={height}
      onLoad={handleFrameLoad}
      sandbox="allow-scripts"
      srcDoc={module.srcDoc}
      title={payload.resultLabel}
    />
  );
}

export default PlatformPluginToolResultSlots;
