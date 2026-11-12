import { useEffect, useState } from 'react';

import {
  createVerifiedSignedSlotDocumentV2,
  type SignedSlotResourceV2,
} from '@agistack/plugin-slots';

type Resource = Omit<SignedSlotResourceV2, 'target'> | null;

/** Desktop mount for a digest-checked slot document. A null resource clears the frame. */
export function DesktopSignedBusinessMount({ resource }: { resource: Resource }) {
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
      'desktop-signed',
    ).then((value) => {
      if (!cancelled) setHtml(value);
    });
    return () => {
      cancelled = true;
      setHtml(null);
    };
  }, [resource]);
  if (html === null) return null;
  return <iframe title="desktop-signed-business" sandbox="allow-scripts" srcDoc={html} />;
}
