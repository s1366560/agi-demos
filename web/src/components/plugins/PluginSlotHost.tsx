import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { useTranslation } from 'react-i18next';

import {
  decodeSlotPortMessageV2,
  encodeSlotPortMessageV2,
  matchesSlotBridgeIdentityV2,
  type SlotActionV2,
  type SlotContextV2,
} from '@agistack/plugin-slots';

import { createPluginSlotDocumentV2 } from '@/services/pluginSlotResourceV2';

import type { UiSlotDefinition } from '@/types/pluginSlots';

export interface PluginSlotHostProps {
  readonly slot: UiSlotDefinition;
  readonly generationId?: string | undefined;
  readonly initPayload?: SlotContextV2 | undefined;
  readonly onAction?: (action: SlotActionV2) => void;
  readonly onError?: ((message: string) => void) | undefined;
  readonly fallback?: ReactNode;
}

export function PluginSlotHost({
  slot,
  generationId = 'standalone',
  initPayload,
  onAction,
  onError,
  fallback,
}: PluginSlotHostProps) {
  const { t } = useTranslation();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const portRef = useRef<MessagePort | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const callbacks = useRef({ initPayload, onAction, onError });
  useLayoutEffect(() => {
    callbacks.current = { initPayload, onAction, onError };
  }, [initPayload, onAction, onError]);
  const [attempt, setAttempt] = useState(0);
  const [height, setHeight] = useState(32);
  const [phase, setPhase] = useState<'loading' | 'ready' | 'failed'>('loading');
  const identity = useMemo(
    () => ({ slotId: slot.id, instanceNonce: crypto.randomUUID(), generationId }),
    // Replacing a resource or retrying retires the previous port, even for the same slot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [slot.id, slot.moduleRef, generationId, attempt]
  );
  const document = useMemo(
    () => createPluginSlotDocumentV2(slot.moduleRef, identity),
    [slot.moduleRef, identity]
  );

  const closePort = useCallback(() => {
    clearTimeout(timerRef.current);
    portRef.current?.postMessage(encodeSlotPortMessageV2(identity, { type: 'slot:dispose' }));
    portRef.current?.close();
    portRef.current = null;
  }, [identity]);
  const [previousIdentity, setPreviousIdentity] = useState(identity);
  if (previousIdentity !== identity) {
    setPreviousIdentity(identity);
    setPhase('loading');
    setHeight(32);
  }
  useEffect(() => closePort, [closePort]);
  useEffect(() => {
    if (phase === 'ready')
      portRef.current?.postMessage(
        encodeSlotPortMessageV2(identity, { type: 'slot:init', payload: initPayload })
      );
  }, [identity, initPayload, phase]);

  const connect = () => {
    closePort();
    const frame = iframeRef.current?.contentWindow;
    if (!frame || !document) return;
    const channel = new MessageChannel();
    const port = channel.port1;
    portRef.current = port;
    let ready = false;
    const fail = (message: string) => {
      if (portRef.current !== port) return;
      setPhase('failed');
      callbacks.current.onError?.(message);
      closePort();
    };
    port.onmessage = (event) => {
      if (portRef.current !== port) return;
      const message = decodeSlotPortMessageV2(event.data);
      if (!message || !matchesSlotBridgeIdentityV2(message, identity)) return;
      switch (message.type) {
        case 'slot:ready':
          ready = true;
          clearTimeout(timerRef.current);
          setPhase('ready');
          port.postMessage(
            encodeSlotPortMessageV2(identity, {
              type: 'slot:init',
              payload: callbacks.current.initPayload,
            })
          );
          break;
        case 'slot:resize':
          if (!ready) return;
          setHeight(Math.min(message.height, 600));
          break;
        case 'slot:action':
          if (!ready) return;
          callbacks.current.onAction?.(message.action);
          break;
        case 'slot:error':
          fail(message.message);
          break;
      }
    };
    port.onmessageerror = () => {
      fail('slot_message_invalid');
    };
    port.start();
    timerRef.current = setTimeout(() => {
      fail('slot_handshake_timeout');
    }, 4000);
    // Opaque sandbox origins require '*'. Only this exact frame receives the one-use port;
    // owner context and actions subsequently travel on the private, identity-bound channel.
    frame.postMessage(encodeSlotPortMessageV2(identity, { type: 'slot:connect' }), '*', [
      channel.port2,
    ]);
  };

  if (!document || phase === 'failed')
    return (
      <div role="status" data-testid={`plugin-slot-fallback-${slot.id}`}>
        {fallback ?? t('plugins.rendererUnavailable')}
        {document && (
          <button
            type="button"
            onClick={() => {
              setPhase('loading');
              setAttempt((value) => value + 1);
            }}
          >
            {t('plugins.retryRenderer')}
          </button>
        )}
      </div>
    );
  return (
    <iframe
      key={identity.instanceNonce}
      ref={iframeRef}
      title={`plugin-slot-${slot.pluginId}-${slot.id}`}
      data-testid={`plugin-slot-${slot.id}`}
      data-ready={phase === 'ready'}
      srcDoc={document}
      sandbox="allow-scripts"
      onLoad={connect}
      style={{ border: 'none', width: '100%', height }}
    />
  );
}
