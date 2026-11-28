import { freezeImagePreviewCarriersV2 } from '../../plugins/desktopStructuredImagePreviewContractV2';
import type { StructuredImagePreviewClientV2 } from '../../plugins/desktopStructuredImagePreviewAuthorityModuleV2';
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { Components } from 'react-markdown';

import { useI18n } from '../../i18n';
import { resolveMarkdownArtifactImage } from './markdownArtifactImageModel';

const MAX_MARKDOWN_IMAGE_BYTES = 25 * 1024 * 1024;
type ImageContext = { client: StructuredImagePreviewClientV2 | null; carriers: readonly unknown[] };
const MarkdownArtifactContext = createContext<ImageContext>({ client: null, carriers: [] });

export function MarkdownArtifactImageProvider({
  client,
  carriers,
  children,
}: {
  client: StructuredImagePreviewClientV2 | null;
  carriers: readonly unknown[];
  children: ReactNode;
}) {
  const value = useMemo(() => ({ client, carriers }), [client, carriers]);
  return (
    <MarkdownArtifactContext.Provider value={value}>{children}</MarkdownArtifactContext.Provider>
  );
}

type ImageRequest = ImageContext & { source: string; resolutionKey: string | null };
type LoadedImage =
  | {
      request: ImageRequest;
      status: 'ready';
      objectUrl: string;
      release: () => void;
      isActive: () => boolean;
    }
  | { request: ImageRequest; status: 'failed' };

export const MarkdownArtifactImage: NonNullable<Components['img']> = ({ src, alt, title }) => {
  const { t } = useI18n();
  const { client, carriers } = useContext(MarkdownArtifactContext);
  const source = typeof src === 'string' ? src : '';
  const label = typeof alt === 'string' && alt.trim() ? alt.trim() : t('chat.markdownImage');
  const validatedCarriers = useMemo(() => {
    if (!client) return null;
    try {
      return freezeImagePreviewCarriersV2(carriers, client.owner);
    } catch {
      return null;
    }
  }, [carriers, client]);
  const resolution = useMemo(
    () =>
      source && validatedCarriers ? resolveMarkdownArtifactImage(source, validatedCarriers) : null,
    [validatedCarriers, source],
  );
  const shellRef = useRef<HTMLSpanElement>(null);
  const [eligible, setEligible] = useState(() => typeof IntersectionObserver === 'undefined');
  const [loaded, setLoaded] = useState<LoadedImage | null>(null);
  const acceptedClient = validatedCarriers ? client : null;
  const requestKey = resolution ? `${resolution.key}\u0000${resolution.mimeType}` : null;
  const currentRequest = useRef<ImageRequest | null>(null);
  // Streaming tokens may replace the carrier array without changing the image.
  // Validate every new array first; retain only the already validated request
  // snapshot while its owner/client and exact resolved image stay unchanged.
  if (
    !currentRequest.current ||
    currentRequest.current.client !== acceptedClient ||
    currentRequest.current.source !== source ||
    currentRequest.current.resolutionKey !== requestKey
  ) {
    currentRequest.current = {
      client: acceptedClient,
      carriers: validatedCarriers ?? [],
      source,
      resolutionKey: requestKey,
    };
  }
  const request = currentRequest.current;

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
    if (!eligible || !request.resolutionKey || !request.client) return;
    const activeClient = request.client;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    let current = true;
    const release = () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
    };
    setLoaded(null);

    void (async () => {
      try {
        const blob = await activeClient.loadImage({
          source: request.source,
          carriers: request.carriers,
          signal: controller.signal,
        });
        if (blob.size > MAX_MARKDOWN_IMAGE_BYTES || !blob.type.toLowerCase().startsWith('image/')) {
          throw new Error('Artifact response is not a supported inline image');
        }
        if (!current || controller.signal.aborted || currentRequest.current !== request) return;
        objectUrl = URL.createObjectURL(blob);
        setLoaded({
          request,
          status: 'ready',
          objectUrl,
          release,
          isActive: () =>
            current && !controller.signal.aborted && currentRequest.current === request,
        });
      } catch (error) {
        if (!current || controller.signal.aborted || currentRequest.current !== request) return;
        setLoaded({ request, status: 'failed' });
      }
    })();

    return () => {
      current = false;
      controller.abort();
      release();
    };
  }, [eligible, request]);

  const currentLoaded = loaded?.request === request ? loaded : null;
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
            if (!currentLoaded.isActive()) return;
            currentLoaded.release();
            setLoaded({ request: currentLoaded.request, status: 'failed' });
          }}
        />
      </span>
    );
  }

  const unavailable = !client || !resolution || currentLoaded?.status === 'failed';
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
