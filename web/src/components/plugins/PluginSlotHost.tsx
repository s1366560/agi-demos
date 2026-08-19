/**
 * Sandboxed iframe host for plugin slot renderers (P3).
 *
 * The host mounts a slot's module inside a sandboxed iframe, performs the
 * protocol handshake, forwards slot events, and enforces the contract
 * client-side: only builtin module references, `ui.*` permissions, and
 * sandboxed rendering. External modules are rejected by the service before
 * they ever reach this component.
 */

import { useEffect, useRef, useState } from 'react';

import {
  decodeSlotMessage,
  encodeSlotMessage,
  isGuestMessageForSlot,
} from '@/services/pluginSlotProtocol';

import type { UiSlotDefinition } from '@/types/pluginSlots';

export interface PluginSlotHostProps {
  slot: UiSlotDefinition;
  initPayload?: unknown;
  onAction?: (name: string, data?: unknown) => void;
  onError?: (message: string) => void;
}

const MODULE_BASE = '/api/v1/platform-plugin-modules/';

export function PluginSlotHost({ slot, initPayload, onAction, onError }: PluginSlotHostProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState<number | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const listener = (event: MessageEvent) => {
      const frameWindow = iframeRef.current?.contentWindow;
      if (frameWindow === null || frameWindow === undefined) return;
      if (event.source !== frameWindow) return;
      const message = decodeSlotMessage(event.data);
      if (message === null || !isGuestMessageForSlot(message, slot.id)) return;
      switch (message.type) {
        case 'slot:ready':
          setReady(true);
          iframeRef.current?.contentWindow?.postMessage(
            encodeSlotMessage({ type: 'slot:init', slotId: slot.id, payload: initPayload }),
            window.location.origin
          );
          break;
        case 'slot:resize':
          if (Number.isFinite(message.height) && message.height > 0) {
            setHeight(message.height);
          }
          break;
        case 'slot:action':
          onAction?.(message.name, message.data);
          break;
        case 'slot:error':
          onError?.(message.message);
          break;
      }
    };
    window.addEventListener('message', listener);
    return () => { window.removeEventListener('message', listener); };
  }, [slot.id, initPayload, onAction, onError]);

  const src = `${MODULE_BASE}${encodeURIComponent(slot.moduleRef.replace(/^builtin:/, ''))}`;

  return (
    <iframe
      ref={iframeRef}
      title={`plugin-slot-${slot.pluginId}-${slot.id}`}
      data-testid={`plugin-slot-${slot.id}`}
      data-ready={ready}
      src={src}
      sandbox="allow-scripts"
      style={{
        border: 'none',
        width: '100%',
        height: height === null ? 120 : height,
      }}
    />
  );
}

export default PluginSlotHost;
