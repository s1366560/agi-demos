import { useEffect, useState } from 'react';

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
}: {
  readonly document: SignedBusinessDocumentV2 | null;
}) {
  const [html, setHtml] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (document === null) {
      setHtml(null);
      return () => {
        cancelled = true;
      };
    }
    void createVerifiedSignedSlotDocumentV2(
      { ...document, target: 'web' },
      'signed-business'
    ).then((value) => {
      if (!cancelled) setHtml(value);
    });
    return () => {
      cancelled = true;
      setHtml(null);
    };
  }, [document]);
  if (html === null) return null;
  return (
    <iframe
      title="signed-business-slot"
      data-testid="signed-business-slot"
      sandbox="allow-scripts"
      srcDoc={html}
    />
  );
}
