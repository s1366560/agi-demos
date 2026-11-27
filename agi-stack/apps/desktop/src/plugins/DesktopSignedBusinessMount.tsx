import { useEffect, useRef, useState } from 'react';

import {
  createVerifiedSignedSlotDocumentV2,
  type SignedSlotResourceV2,
} from '@agistack/plugin-slots';

type Resource = Omit<SignedSlotResourceV2, 'target'> | null;

/** Desktop mount for a digest-checked slot document. A null resource clears the frame. */
export function DesktopSignedBusinessMount({
  resource,
  onAction,
}: {
  resource: Resource;
  onAction?: (id: string, payload?: Record<string, unknown>) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    if (!resource || !onAction) return;
    const receive = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow || event.origin !== 'null')
        return;
      const message = event.data;
      if (
        message?.source === 'memstack-plugin-slot' &&
        message.type === 'slot:action' &&
        message.action?.type === 'plugin.ui' &&
        typeof message.action.id === 'string' &&
        (message.action.payload === undefined ||
          (message.action.payload !== null &&
            typeof message.action.payload === 'object' &&
            !Array.isArray(message.action.payload)))
      ) {
        if (message.action.payload === undefined) onAction(message.action.id);
        else onAction(message.action.id, message.action.payload);
      }
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [resource, onAction]);
  const [html, setHtml] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (resource === null) {
      setHtml(null);
      return () => {
        cancelled = true;
      };
    }
    void createVerifiedSignedSlotDocumentV2(
      { ...resource, target: 'desktop-renderer' },
      'desktop-signed'
    ).then((value) => {
      if (!cancelled) setHtml(value);
    });
    return () => {
      cancelled = true;
      setHtml(null);
    };
  }, [resource]);
  if (html === null) return null;
  return (
    <iframe ref={frame} title="desktop-signed-business" sandbox="allow-scripts" srcDoc={html} />
  );
}
