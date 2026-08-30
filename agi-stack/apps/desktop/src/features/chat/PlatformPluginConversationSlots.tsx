/** Desktop V2 conversation-slot outlet. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  decodeSlotMessage,
  encodeSlotMessage,
  isGuestMessageForSlot,
} from '@agistack/plugin-slots';

import { useI18n } from '../../i18n';
import { useDesktopRendererGenerationV2 } from '../../plugins/desktopRendererGenerationContextV2';
import type { DesktopConversationRendererModuleV2 } from '../../plugins/desktopConversationRendererModuleV2';
import type { AuthorizedUiSlotDefinitionV2 } from '../../plugins/uiSlotRegistry';
import { usePlatformPluginUiSlots } from '../settings/usePlatformPluginUiSlots';
import {
  createDesktopConversationRendererPayloadV2,
  DesktopConversationRendererBridgeV2,
  type DesktopConversationRendererPayloadV2,
  type DesktopConversationRendererProtocolV2,
  type DesktopConversationRendererWorkflowTargetV2,
} from './desktopConversationRendererBridgeV2';

const CONVERSATION_RENDERER_PROTOCOL_V2: DesktopConversationRendererProtocolV2 =
  Object.freeze({
    decode: decodeSlotMessage,
    encode: encodeSlotMessage,
    isGuestForSlot: isGuestMessageForSlot,
  });

export interface PlatformPluginConversationSlotsProps {
  readonly active: boolean;
  readonly conversationId: string | null | undefined;
  readonly disabled: boolean;
  readonly messageCount: number;
  readonly onOpenCommands: (trigger?: HTMLElement | null) => void;
  readonly sending: boolean;
  readonly workflowTarget: DesktopConversationRendererWorkflowTargetV2;
}

export function PlatformPluginConversationSlots({
  active,
  conversationId,
  disabled,
  messageCount,
  onOpenCommands,
  sending,
  workflowTarget,
}: PlatformPluginConversationSlotsProps) {
  const { t } = useI18n();
  const { composition } = useDesktopRendererGenerationV2();
  const { slots, error, loading } = usePlatformPluginUiSlots({ active });
  const [hostError, setHostError] = useState<string | null>(null);
  const payload = useMemo(
    () =>
      createDesktopConversationRendererPayloadV2({
        commandsLabel: t('composer.commands'),
        conversationId,
        disabled,
        messageCount,
        sending,
        workflowTarget,
      }),
    [conversationId, disabled, messageCount, sending, t, workflowTarget],
  );
  const visible = slots.filter((slot) => slot.slot === 'conversation_renderer');
  if (visible.length === 0) return null;

  return (
    <section
      className="platform-plugin-conversation-slots"
      aria-live="polite"
      data-loading={loading || undefined}
      data-error={hostError ?? error ?? undefined}
    >
      {visible.map((slot) => {
        const module = composition.resolveConversationRendererModule(slot);
        if (module === null) return null;
        return (
          <DesktopConversationRendererFrameV2
            key={`${slot.pluginId}:${slot.id}`}
            module={module}
            onError={setHostError}
            onOpenCommands={onOpenCommands}
            payload={payload}
            slot={slot}
          />
        );
      })}
    </section>
  );
}

function DesktopConversationRendererFrameV2({
  module,
  onError,
  onOpenCommands,
  payload,
  slot,
}: Readonly<{
  module: DesktopConversationRendererModuleV2;
  onError: (errorCode: string) => void;
  onOpenCommands: (trigger?: HTMLElement | null) => void;
  payload: DesktopConversationRendererPayloadV2;
  slot: AuthorizedUiSlotDefinitionV2;
}>) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const bridgeRef = useRef<DesktopConversationRendererBridgeV2 | null>(null);
  const frameLoadedRef = useRef(false);
  const onOpenCommandsRef = useRef(onOpenCommands);
  const payloadRef = useRef(payload);
  const [height, setHeight] = useState(48);
  onOpenCommandsRef.current = onOpenCommands;
  payloadRef.current = payload;

  const handleFrameLoad = useCallback(() => {
    frameLoadedRef.current = true;
    bridgeRef.current?.activate();
  }, []);

  useEffect(() => {
    const frameWindow = iframeRef.current?.contentWindow;
    if (frameWindow === null || frameWindow === undefined) return;
    const bridge = new DesktopConversationRendererBridgeV2({
      frameWindow,
      onAction: () => onOpenCommandsRef.current(),
      onError,
      onResize: setHeight,
      payload: payloadRef.current,
      protocol: CONVERSATION_RENDERER_PROTOCOL_V2,
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
      className="platform-plugin-conversation-frame"
      data-contract={slot.contract}
      data-module-ref={module.moduleRef}
      data-plugin-id={slot.pluginId}
      height={height}
      onLoad={handleFrameLoad}
      sandbox="allow-scripts"
      srcDoc={module.srcDoc}
      title={payload.commandsLabel}
    />
  );
}

export default PlatformPluginConversationSlots;
