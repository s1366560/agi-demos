import { useEffect, useRef, useState } from 'react';

import { createVerifiedSignedSlotDocumentV2 } from '@agistack/plugin-slots';

export interface SignedBusinessDocumentV2 {
  readonly moduleRef: string;
  readonly digest: string;
  readonly source: string;
  readonly bytes: Uint8Array;
}

/** Mount one verified signed document. Unmount drops the document state. */
export function SignedBusinessMount({
  document,
  onAction,
}: {
  readonly document: SignedBusinessDocumentV2 | null;
  readonly onAction?: (id: string, payload?: Record<string, unknown>) => void;
}) {
  const [verified, setVerified] = useState<{ document: SignedBusinessDocumentV2; html: string } | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    if (!document || !onAction) return;
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
  }, [document, onAction]);
  useEffect(() => {
    let cancelled = false;
    if (document === null) return;
    void createVerifiedSignedSlotDocumentV2({ ...document, target: 'web' }, 'signed-business').then(
      (value) => {
        if (!cancelled && value !== null) setVerified({ document, html: value });
      }
    );
    return () => {
      cancelled = true;
    };
  }, [document]);
  if (!verified || verified.document !== document) return null;
  return (
    <iframe
      ref={frame}
      title="signed-business-slot"
      data-testid="signed-business-slot"
      sandbox="allow-scripts"
      srcDoc={verified.html}
    />
  );
}
