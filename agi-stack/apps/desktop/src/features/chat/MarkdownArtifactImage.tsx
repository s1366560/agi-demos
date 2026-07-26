import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { Components } from 'react-markdown';

import { useI18n } from '../../i18n';
import { resolveMarkdownArtifactImage } from './markdownArtifactImageModel';

const MAX_MARKDOWN_IMAGE_BYTES = 25 * 1024 * 1024;
const MarkdownArtifactContext = createContext<readonly unknown[]>([]);

export function MarkdownArtifactImageProvider({
  carriers,
  children,
}: {
  carriers: readonly unknown[];
  children: ReactNode;
}) {
  return (
    <MarkdownArtifactContext.Provider value={carriers}>{children}</MarkdownArtifactContext.Provider>
  );
}

type LoadedImage =
  | { key: string; status: 'ready'; objectUrl: string }
  | { key: string; status: 'failed' };

export const MarkdownArtifactImage: NonNullable<Components['img']> = ({ src, alt, title }) => {
  const { t } = useI18n();
  const carriers = useContext(MarkdownArtifactContext);
  const source = typeof src === 'string' ? src : '';
  const label = typeof alt === 'string' && alt.trim() ? alt.trim() : t('chat.markdownImage');
  const resolution = useMemo(
    () => (source ? resolveMarkdownArtifactImage(source, carriers) : null),
    [carriers, source],
  );
  const shellRef = useRef<HTMLSpanElement>(null);
  const [eligible, setEligible] = useState(() => typeof IntersectionObserver === 'undefined');
  const [loaded, setLoaded] = useState<LoadedImage | null>(null);
  const resolutionKey = resolution?.key ?? null;
  const resolutionUrl = resolution?.url ?? null;

  useEffect(() => {
    if (eligible || !shellRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setEligible(true);
        observer.disconnect();
      },
      { rootMargin: '240px 0px' },
    );
    observer.observe(shellRef.current);
    return () => observer.disconnect();
  }, [eligible]);

  useEffect(() => {
    if (!eligible || !resolutionKey || !resolutionUrl) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    let current = true;
    setLoaded(null);

    void (async () => {
      try {
        const response = await fetch(resolutionUrl, {
          cache: 'no-store',
          credentials: 'omit',
          referrerPolicy: 'no-referrer',
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Artifact image returned ${response.status}`);
        const declaredSize = Number(response.headers.get('content-length'));
        if (Number.isFinite(declaredSize) && declaredSize > MAX_MARKDOWN_IMAGE_BYTES) {
          throw new Error('Artifact image exceeds the inline preview limit');
        }
        const blob = await response.blob();
        if (blob.size > MAX_MARKDOWN_IMAGE_BYTES || !blob.type.toLowerCase().startsWith('image/')) {
          throw new Error('Artifact response is not a supported inline image');
        }
        if (!current) return;
        objectUrl = URL.createObjectURL(blob);
        setLoaded({ key: resolutionKey, status: 'ready', objectUrl });
      } catch (error) {
        if (!current || controller.signal.aborted) return;
        setLoaded({ key: resolutionKey, status: 'failed' });
      }
    })();

    return () => {
      current = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [eligible, resolutionKey, resolutionUrl]);

  const currentLoaded = loaded?.key === resolutionKey ? loaded : null;
  if (currentLoaded?.status === 'ready') {
    return (
      <span className="markdown-artifact-image-shell is-ready">
        <img
          src={currentLoaded.objectUrl}
          alt={label}
          title={typeof title === 'string' ? title : undefined}
          loading="lazy"
          decoding="async"
          className="markdown-artifact-image"
          onError={() => {
            URL.revokeObjectURL(currentLoaded.objectUrl);
            setLoaded({ key: currentLoaded.key, status: 'failed' });
          }}
        />
      </span>
    );
  }

  const unavailable = !resolution || currentLoaded?.status === 'failed';
  return (
    <span
      ref={shellRef}
      className={`markdown-artifact-image-shell ${unavailable ? 'is-unavailable' : 'is-loading'}`}
      role="img"
      aria-label={t(unavailable ? 'chat.markdownImageUnavailable' : 'chat.markdownImageLoading', {
        alt: label,
      })}
    >
      <span>{label}</span>
      <small>
        {t(unavailable ? 'chat.markdownImageUnavailableShort' : 'chat.markdownImageLoadingShort')}
      </small>
    </span>
  );
};
