import { useEffect, useRef, useState } from 'react';
import type { ComputerUseClientV2 } from '../../api/computerUseClientV2';
import { useI18n } from '../../i18n';

/** Recording bytes remain in the owned artifact store until the user requests playback. */
export function ComputerUseAudio({
  client,
  artifactId,
  label,
}: {
  client: ComputerUseClientV2 | null;
  artifactId: string;
  label: string;
}) {
  const { t } = useI18n();
  const [loaded, setLoaded] = useState<{
    client: ComputerUseClientV2;
    artifactId: string;
    url: string;
  } | null>(null);
  const url = loaded?.client === client && loaded.artifactId === artifactId ? loaded.url : null;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    controller.current?.abort();
    controller.current = null;
    setLoaded(null);
    setError(false);
    setLoading(false);
    return () => controller.current?.abort();
  }, [client, artifactId]);
  useEffect(
    () => () => {
      if (loaded) URL.revokeObjectURL(loaded.url);
    },
    [loaded],
  );
  const load = async () => {
    if (!client || loading || controller.current) return;
    const pending = new AbortController();
    controller.current = pending;
    setLoading(true);
    try {
      const blob = await client.audio(artifactId, pending.signal);
      if (!pending.signal.aborted)
        setLoaded({ client, artifactId, url: URL.createObjectURL(blob) });
    } catch {
      if (!pending.signal.aborted) setError(true);
    } finally {
      if (controller.current === pending) controller.current = null;
      if (!pending.signal.aborted) setLoading(false);
    }
  };
  return (
    <div className="tool-computer-audio">
      <span>{label}</span>
      {url ? (
        <audio controls preload="metadata" src={url} aria-label={label} />
      ) : (
        <button type="button" disabled={!client || loading} onClick={() => void load()}>
          {t(loading ? 'cua.loading' : 'cua.audioPreview')}
        </button>
      )}
      {error ? <span role="alert">{t('cua.unavailable')}</span> : null}
    </div>
  );
}
