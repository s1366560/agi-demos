import { useEffect, useState } from 'react';

import type { Components } from 'react-markdown';

import {
  isSafeArtifactUrl,
  looksLikeSandboxImagePath,
  resolveSandboxArtifactUrl,
} from '@/utils/sandboxArtifactPath';

/**
 * Image renderer that resolves sandbox/workspace paths (e.g.
 * `/workspace/output/chart.png`) to the backing artifact's presigned URL.
 *
 * Without this, markdown such as `![](/workspace/output/chart.png)` resolves
 * against the web origin and 404s / returns the SPA HTML, so the image breaks.
 * Absolute URLs render immediately and unchanged.
 */
export const SandboxImage: NonNullable<Components['img']> = ({ src, alt, ...props }) => {
  const initialSrc = typeof src === 'string' ? src : '';
  const needsResolution = !!initialSrc && looksLikeSandboxImagePath(initialSrc);

  // Directly-loadable sources render synchronously; only sandbox paths are resolved
  // asynchronously below. Keying the resolved value by source avoids showing a stale
  // URL when the src prop changes between renders.
  const directSrc = initialSrc && !needsResolution ? initialSrc : null;
  const [resolved, setResolved] = useState<{ key: string; url: string } | null>(null);

  useEffect(() => {
    if (!needsResolution) return;

    const status = { cancelled: false };
    void (async () => {
      const url = await resolveSandboxArtifactUrl(initialSrc);
      if (!url || status.cancelled || !isSafeArtifactUrl(url)) return;
      setResolved({ key: initialSrc, url });
    })();

    return () => {
      status.cancelled = true;
    };
  }, [initialSrc, needsResolution]);

  const finalSrc = directSrc ?? (resolved?.key === initialSrc ? resolved.url : null);
  if (!finalSrc) return null;
  return <img src={finalSrc} alt={typeof alt === 'string' ? alt : ''} {...props} />;
};

export const MarkdownTable: NonNullable<Components['table']> = ({ children, ...props }) => (
  <div className="overflow-x-auto w-full">
    <table {...props}>{children}</table>
  </div>
);
