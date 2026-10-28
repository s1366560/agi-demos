import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  validatedReplMediaV2,
  type ReplOutputPresentationV2,
  type ToolResultMediaV2,
} from '@agistack/plugin-slots';

const EMPTY_MEDIA: readonly ToolResultMediaV2[] = Object.freeze([]);

export function ReplToolResultContentV2({
  presentation,
  media,
  label = '',
}: Readonly<{
  presentation: ReplOutputPresentationV2;
  media?: readonly ToolResultMediaV2[] | undefined;
  label?: string | undefined;
}>) {
  const { t } = useTranslation();
  const content = media ?? EMPTY_MEDIA;
  const [loaded, setLoaded] = useState<Readonly<{
    presentation: ReplOutputPresentationV2;
    media: readonly ToolResultMediaV2[];
    urls: ReadonlyMap<string, string>;
  }> | null>(null);
  useEffect(() => {
    const urls = new Map<string, string>();
    for (const value of validatedReplMediaV2(presentation, content)) {
      const key = value.store + ':' + value.artifactId;
      if (!urls.has(key))
        urls.set(
          key,
          URL.createObjectURL(new Blob([new Uint8Array(value.bytes)], { type: value.mimeType }))
        );
    }
    // Object URLs must be created and published within their cleanup lifecycle.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- publish effect-owned object URLs
    setLoaded({ presentation, media: content, urls });
    return () => {
      for (const url of urls.values()) URL.revokeObjectURL(url);
    };
  }, [presentation, content]);
  const urls =
    loaded?.presentation === presentation && loaded.media === content ? loaded.urls : null;
  return (
    <div>
      {presentation.entries.map((entry, index) => {
        if (entry.kind === 'text')
          return (
            <pre key={index} className="whitespace-pre-wrap">
              {entry.text}
            </pre>
          );
        if (entry.kind === 'unavailable')
          return (
            <span key={index} role="status">
              {t('plugins.rendererUnavailable')}
            </span>
          );
        const url = urls?.get(entry.store + ':' + entry.artifactId);
        if (!url)
          return (
            <span key={index} role="status">
              {t(media === undefined || !urls ? 'common.loading' : 'plugins.rendererUnavailable')}
            </span>
          );
        return entry.kind === 'image' ? (
          <img key={index} src={url} alt={label} className="max-w-full max-h-96 object-contain" />
        ) : (
          <audio key={index} controls preload="metadata" src={url} aria-label={label} />
        );
      })}
    </div>
  );
}
