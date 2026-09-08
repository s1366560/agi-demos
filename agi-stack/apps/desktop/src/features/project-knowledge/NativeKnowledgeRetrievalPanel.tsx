import { useI18n } from '../../i18n';
import { NativeKnowledgeRetrievalResults } from './NativeKnowledgeRetrievalResults';
import type {
  NativeKnowledgeRetrievalController,
  NativeKnowledgeRetrievalMode,
  NativeKnowledgeRetrievalModel,
} from './nativeKnowledgeRetrievalController';

export function NativeKnowledgeRetrievalUnavailable() {
  const { t } = useI18n();
  return (
    <section className="native-knowledge-retrieval">
      <p>{t('nativeRetrieval.unavailable')}</p>
    </section>
  );
}

export function NativeKnowledgeRetrievalPanel({
  model,
  controller,
  disabled = false,
}: Readonly<{
  model: NativeKnowledgeRetrievalModel;
  controller: NativeKnowledgeRetrievalController;
  disabled?: boolean;
}>) {
  const { t } = useI18n();
  const modes = (['text', 'semantic', 'entities', 'relationships'] as const).filter((mode) =>
    model.allowedActions.includes(mode),
  );
  if (!modes.length) return null;
  const help =
    model.mode === 'text'
      ? 'literalHelp'
      : model.mode === 'semantic'
        ? 'semanticHelp'
        : model.mode === 'entities'
          ? 'entityHelp'
          : 'relationshipHelp';
  return (
    <fieldset className="native-knowledge-retrieval" disabled={disabled}>
      <legend>{t('nativeRetrieval.retrieval')}</legend>
      {model.navigation ? (
        <aside>
          <p>{t('nativeRetrieval.navigationHelp')}</p>
          <p>
            {t('nativeRetrieval.source')}: {model.navigation.source.memory_id}
          </p>
          <p>
            {t('nativeRetrieval.sourceRevision')}: {model.navigation.source.revision}
          </p>
          <button type="button" onClick={() => controller.clearNavigation()}>
            {t('nativeRetrieval.clearNavigation')}
          </button>
        </aside>
      ) : null}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void controller.submit();
        }}
      >
        <label>
          {t('nativeRetrieval.mode')}
          <select
            value={model.mode ?? ''}
            onChange={(event) =>
              controller.setMode(event.target.value as NativeKnowledgeRetrievalMode)
            }
          >
            {modes.map((mode) => (
              <option key={mode} value={mode}>
                {t(`nativeRetrieval.${mode}`)}
              </option>
            ))}
          </select>
        </label>
        <p>{t(`nativeRetrieval.${help}`)}</p>
        {model.mode === 'text' || model.mode === 'semantic' ? (
          <label>
            {t('nativeRetrieval.query')}
            <input
              value={model.draft}
              onChange={(event) => controller.setDraft(event.target.value)}
            />
          </label>
        ) : null}
        <button type="submit" disabled={model.phase === 'loading' || model.phase === 'unavailable'}>
          {t('nativeRetrieval.submit')}
        </button>
      </form>
      {model.phase === 'loading' ? <p role="status">{t('nativeRetrieval.loading')}</p> : null}
      {model.error ? <p role="alert">{t(`nativeRetrieval.${model.error}`)}</p> : null}
      <NativeKnowledgeRetrievalResults model={model} controller={controller} />
    </fieldset>
  );
}
