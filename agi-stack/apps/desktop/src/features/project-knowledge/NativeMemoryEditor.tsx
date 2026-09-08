import { NativeKnowledgeMetadataField } from './NativeKnowledgeMetadataField';
import { useI18n } from '../../i18n';
import type { NativeMemoriesController, NativeMemoriesModel } from './nativeMemoriesController';

export function NativeMemoryEditor({
  model,
  controller,
}: Readonly<{
  model: NativeMemoriesModel;
  controller: NativeMemoriesController;
}>) {
  const { t } = useI18n();
  const editing = model.phase === 'creating' || model.phase === 'editing';
  const locked = model.phase === 'saving' || model.phase === 'uncertain';
  const allowed = (action: string) => model.allowedActions.includes(action);
  return (
    <section
      className="native-memory-editor"
      aria-label={t('nativeMemories.view')}
      aria-busy={model.phase === 'saving'}
    >
      {model.error ? <p role="alert">{t(`nativeMemories.${model.error}`)}</p> : null}
      {model.notice ? <p role="status">{t('nativeMemories.accepted')}</p> : null}
      {model.phase === 'loading' ? <p role="status">{t('nativeMemories.loading')}</p> : null}
      {model.record ? (
        <article>
          <h2>{model.record.title}</h2>
          {!model.draft ? <p style={{ whiteSpace: 'pre-wrap' }}>{model.record.content}</p> : null}
          <dl>
            <dt>{t('nativeMemories.version')}</dt>
            <dd>{model.record.version}</dd>
            <dt>{t('nativeMemories.author')}</dt>
            <dd>{model.record.author_id}</dd>
            <dt>{t('nativeMemories.contentType')}</dt>
            <dd>{model.record.content_type}</dd>
          </dl>
          {!model.draft ? (
            <details>
              <summary>{t('nativeMemories.metadataLabel')}</summary>
              <pre>{JSON.stringify(model.record.metadata, null, 2)}</pre>
            </details>
          ) : null}
        </article>
      ) : null}
      {model.draft ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void controller.save();
          }}
        >
          <fieldset disabled={!editing}>
            <label>
              {t('nativeMemories.titleLabel')}
              <input
                value={model.draft.title}
                onChange={(event) => controller.setDraft({ title: event.target.value })}
              />
            </label>
            <label>
              {t('nativeMemories.contentLabel')}
              <textarea
                rows={8}
                value={model.draft.content}
                onChange={(event) => controller.setDraft({ content: event.target.value })}
              />
            </label>
            <NativeKnowledgeMetadataField
              value={model.draft.metadataText}
              invalid={model.error === 'invalidMetadata'}
              onChange={(metadataText) => controller.setDraft({ metadataText })}
            />
            {editing && allowed(model.phase === 'creating' ? 'create' : 'update') ? (
              <button type="submit">{t('common.save')}</button>
            ) : null}
          </fieldset>
        </form>
      ) : null}
      {model.phase === 'saving' ? <p role="status">{t('nativeMemories.saving')}</p> : null}
      {model.phase === 'uncertain' ? (
        <button type="button" onClick={() => void controller.retryWrite()}>
          {t('nativeMemories.retryWrite')}
        </button>
      ) : null}
      {model.phase === 'confirming_delete' && allowed('delete') ? (
        <div>
          <p>{t('nativeMemories.deleteConfirm')}</p>
          <button type="button" onClick={() => void controller.confirmDelete()}>
            {t('common.delete')}
          </button>
        </div>
      ) : null}
      {model.phase === 'viewing' && model.record && allowed('view') ? (
        <div>
          {allowed('update') ? (
            <button type="button" onClick={() => void controller.open(model.record!.id, 'edit')}>
              {t('nativeMemories.edit')}
            </button>
          ) : null}
          {allowed('delete') ? (
            <button type="button" onClick={() => void controller.open(model.record!.id, 'delete')}>
              {t('nativeMemories.delete')}
            </button>
          ) : null}
        </div>
      ) : null}
      {(model.phase === 'conflict' || model.phase === 'error') &&
      model.record &&
      allowed('view') ? (
        <button type="button" onClick={() => void controller.reload()}>
          {t('nativeMemories.reload')}
        </button>
      ) : null}
      {model.phase !== 'idle' && model.phase !== 'unavailable' && !locked ? (
        <button type="button" onClick={controller.close}>
          {t('common.close')}
        </button>
      ) : null}
    </section>
  );
}
