import { useI18n } from '../../i18n';
import type { CloudMemoriesController, CloudMemoriesModel } from './cloudMemoriesController';

export function CloudMemoryEditor({
  model,
  controller,
}: Readonly<{ model: CloudMemoriesModel; controller: CloudMemoriesController }>) {
  const { t } = useI18n();
  const locked = ['saving', 'uncertain', 'loading'].includes(model.phase);
  const editable = ['creating', 'editing'].includes(model.phase);
  return (
    <section className="cloud-memory-editor" aria-label={t('cloudMemories.editor')}>
      {model.phase === 'loading' ? <p role="status">{t('cloudMemories.loadingDetail')}</p> : null}
      {model.record ? (
        <>
          <h2>{model.record.title}</h2>
          <p className="cloud-memory-body">{model.record.content}</p>
          <dl>
            <dt>{t('cloudMemories.revision')}</dt>
            <dd>{model.record.version}</dd>
            <dt>{t('cloudMemories.contentType')}</dt>
            <dd>{model.record.contentType}</dd>
          </dl>
        </>
      ) : null}
      {model.draft ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void controller.save();
          }}
        >
          <label>
            {t('cloudMemories.memoryTitle')}
            <input
              value={model.draft.title}
              readOnly={!editable}
              onChange={(event) =>
                controller.setDraft({ ...model.draft!, title: event.target.value })
              }
            />
          </label>
          <label>
            {t('cloudMemories.content')}
            <textarea
              rows={7}
              value={model.draft.content}
              readOnly={!editable}
              onChange={(event) =>
                controller.setDraft({ ...model.draft!, content: event.target.value })
              }
            />
          </label>
          {model.intent === 'create' ? <p>{t('cloudMemories.newType')}</p> : null}
          {editable ? (
            <button type="submit" disabled={model.listState !== 'ready'}>
              {t('cloudMemories.save')}
            </button>
          ) : null}
        </form>
      ) : null}
      {model.phase === 'deleting' ? (
        <>
          <p>{t('cloudMemories.deleteConfirmation')}</p>
          <button
            type="button"
            disabled={model.listState !== 'ready'}
            onClick={() => void controller.confirmDelete()}
          >
            {t('cloudMemories.confirmDelete')}
          </button>
        </>
      ) : null}
      {model.phase === 'saving' ? <p role="status">{t('cloudMemories.saving')}</p> : null}
      {model.phase === 'uncertain' ? (
        <>
          <p role="alert">{t('cloudMemories.uncertain')}</p>
          <button type="button" onClick={() => void controller.retryWrite()}>
            {t('cloudMemories.retrySame')}
          </button>
        </>
      ) : null}
      {model.phase === 'conflict' ? (
        <>
          <p>{t('cloudMemories.conflictHelp')}</p>
          <button type="button" onClick={() => void controller.reloadConflict()}>
            {t('cloudMemories.reloadLatest')}
          </button>
        </>
      ) : null}
      {model.phase === 'reviewing' ? (
        <section aria-label={t('cloudMemories.latestVersion')}>
          <h3>{t('cloudMemories.latestVersion')}</h3>
          {model.latest ? (
            <>
              <h4>{model.latest.title}</h4>
              <p className="cloud-memory-body">{model.latest.content}</p>
              <p>
                {t('cloudMemories.revision')}: {model.latest.version}
              </p>
            </>
          ) : null}
          <p>{t('cloudMemories.reviewHelp')}</p>
          <button type="button" onClick={controller.adoptLatest}>
            {t('cloudMemories.reviewLatest')}
          </button>
        </section>
      ) : null}
      {model.error ? <p role="alert">{t(`cloudMemories.${model.error}`)}</p> : null}
      {model.notice ? <p role="status">{t(`cloudMemories.${model.notice}`)}</p> : null}
      {model.intent ? (
        <button type="button" disabled={locked} onClick={controller.close}>
          {t('common.close')}
        </button>
      ) : null}
    </section>
  );
}
