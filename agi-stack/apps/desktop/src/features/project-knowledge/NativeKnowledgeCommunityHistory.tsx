import { useI18n } from '../../i18n';
import type {
  NativeKnowledgeCommunityController,
  NativeKnowledgeCommunityModel,
} from './nativeKnowledgeCommunityController';

function CreatedTime({ timestamp, locale }: Readonly<{ timestamp: number; locale: string }>) {
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) return <span>{timestamp}</span>;
  return <time dateTime={date.toISOString()}>{date.toLocaleString(locale)}</time>;
}

/** History receipts identify durable builds; their initial state is not presented as current status. */
export function NativeKnowledgeCommunityHistory({
  model,
  controller,
}: Readonly<{
  model: NativeKnowledgeCommunityModel;
  controller: NativeKnowledgeCommunityController;
}>) {
  const { t, locale } = useI18n();
  if (!model.allowedActions.includes('community_builds')) return null;
  const busy = ['loading', 'executing', 'unavailable'].includes(model.phase);
  const history = model.history;
  return (
    <section aria-label={t('nativeCommunity.history')}>
      <h2>{t('nativeCommunity.history')}</h2>
      <button type="button" disabled={busy} onClick={() => void controller.loadHistory()}>
        {t('nativeCommunity.loadHistory')}
      </button>
      {history ? (
        <>
          <ol>
            {history.items.map((build) => (
              <li key={build.build_id}>
                <p>{build.build_id}</p>
                <p>
                  {t('nativeCommunity.created')}:{' '}
                  <CreatedTime timestamp={build.created_at_ms} locale={locale} /> ·{' '}
                  {t('nativeCommunity.candidates')}: {build.candidate_count}
                </p>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void controller.refresh(build.build_id)}
                >
                  {t('nativeCommunity.open')}
                </button>
              </li>
            ))}
          </ol>
          {history.items.length === 0 ? <p>{t('nativeCommunity.noHistory')}</p> : null}
          <nav aria-label={t('nativeCommunity.history')}>
            <button
              type="button"
              disabled={busy || history.offset === 0}
              onClick={() =>
                void controller.loadHistory(Math.max(0, history.offset - history.limit))
              }
            >
              {t('nativeCommunity.previous')}
            </button>
            <span>
              {Math.min(history.offset + 1, history.total)}–
              {Math.min(history.offset + history.limit, history.total)} / {history.total}
            </span>
            <button
              type="button"
              disabled={busy || history.offset + history.limit >= history.total}
              onClick={() => void controller.loadHistory(history.offset + history.limit)}
            >
              {t('nativeCommunity.next')}
            </button>
          </nav>
        </>
      ) : null}
    </section>
  );
}
