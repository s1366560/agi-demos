import { useI18n } from '../../i18n';
import type {
  NativeKnowledgeEntityReference,
  NativeKnowledgeProcessingSource,
} from './nativeKnowledgeContracts';
import type {
  NativeKnowledgeRetrievalController,
  NativeKnowledgeRetrievalModel,
} from './nativeKnowledgeRetrievalController';

export function NativeKnowledgeRetrievalResults({
  model,
  controller,
}: Readonly<{
  model: NativeKnowledgeRetrievalModel;
  controller: NativeKnowledgeRetrievalController;
}>) {
  const { t } = useI18n();
  const snapshot = model.result;
  if (!snapshot) return null;
  const reference = (source: NativeKnowledgeProcessingSource, audit: number) => (
    <>
      <dl>
        <dt>{t('nativeRetrieval.source')}</dt>
        <dd>{source.memory_id}</dd>
        <dt>{t('nativeRetrieval.sourceRevision')}</dt>
        <dd>{source.revision}</dd>
        <dt>{t('nativeRetrieval.changeSequence')}</dt>
        <dd>{source.change_sequence}</dd>
        <dt>{t('nativeRetrieval.auditAttempt')}</dt>
        <dd>{audit}</dd>
      </dl>
      {model.allowedActions.includes('view') ? (
        <button
          type="button"
          disabled={model.phase === 'loading' || model.sourceState === 'loading'}
          onClick={() => void controller.viewSource(source)}
        >
          {t('nativeRetrieval.viewSource')}
        </button>
      ) : null}
    </>
  );
  const identity = (source: NativeKnowledgeProcessingSource) =>
    JSON.stringify([source.memory_id, source.revision, source.change_sequence]);
  const selected = (reference: NativeKnowledgeEntityReference) =>
    model.navigation &&
    reference.entity_index === model.navigation.entity_index &&
    identity(reference.source) === identity(model.navigation.source);
  const navigation = (
    mode: 'entities' | 'relationships',
    reference: NativeKnowledgeEntityReference,
  ) =>
    model.allowedActions.includes(mode) ? (
      <button
        type="button"
        disabled={model.phase === 'loading'}
        onClick={() => void controller.navigateReference(mode, reference)}
      >
        {t(
          mode === 'entities'
            ? 'nativeRetrieval.viewEntity'
            : 'nativeRetrieval.viewSourceRelationships',
        )}
      </button>
    ) : null;
  const empty =
    snapshot.operation === 'semantic'
      ? snapshot.result.hits.length === 0
      : snapshot.result.items.length === 0;
  return (
    <>
      {empty ? <p>{t('nativeRetrieval.noResults')}</p> : null}
      <ol>
        {snapshot.operation === 'text'
          ? snapshot.result.items.map((hit) => (
              <li key={identity(hit.source)}>
                <h3>{hit.title}</h3>
                <pre>{hit.content}</pre>
                {reference(hit.source, hit.audit_attempt)}
              </li>
            ))
          : null}
        {snapshot.operation === 'semantic'
          ? snapshot.result.hits.map((hit) => (
              <li key={identity(hit.input.source)}>
                <p>
                  {t('nativeRetrieval.score')}: {hit.score.toFixed(4)}
                </p>
                {reference(hit.input.source, hit.input.audit_attempt)}
              </li>
            ))
          : null}
        {snapshot.operation === 'entities'
          ? snapshot.result.items.map((item) => (
              <li key={`${identity(item.reference.source)}:${item.reference.entity_index}`}>
                <h3>{item.entity.name}</h3>
                {selected(item.reference) ? <p>{t('nativeRetrieval.selectedEntity')}</p> : null}
                <p>
                  {t('nativeRetrieval.entityKind')}: {item.entity.kind}
                </p>
                {reference(item.reference.source, item.audit_attempt)}
                {navigation('relationships', item.reference)}
              </li>
            ))
          : null}
        {snapshot.operation === 'relationships'
          ? snapshot.result.items.map((item) => (
              <li key={`${identity(item.source)}:${item.relationship_index}`}>
                <h3>{item.relationship.relation_type}</h3>
                <p>{item.relationship.fact}</p>
                {selected(item.source_entity) || selected(item.target_entity) ? (
                  <p>{t('nativeRetrieval.referencesSelectedEntity')}</p>
                ) : null}
                <dl>
                  <dt>{t('nativeRetrieval.sourceReference')}</dt>
                  <dd>
                    {item.source_entity.source.memory_id} / {item.source_entity.entity_index}
                    {navigation('entities', item.source_entity)}
                  </dd>
                  <dt>{t('nativeRetrieval.targetReference')}</dt>
                  <dd>
                    {item.target_entity.source.memory_id} / {item.target_entity.entity_index}
                    {navigation('entities', item.target_entity)}
                  </dd>
                </dl>
                {reference(item.source, item.audit_attempt)}
              </li>
            ))
          : null}
      </ol>
      {snapshot.operation !== 'semantic' ? (
        <>
          {snapshot.result.next_cursor ? (
            <button
              type="button"
              disabled={model.phase === 'loading'}
              onClick={() => void controller.nextPage()}
            >
              {t('nativeRetrieval.next')}
            </button>
          ) : null}
          <p>{t('nativeRetrieval.cursorHelp')}</p>
        </>
      ) : null}
      {model.sourceState === 'loading' ? <p role="status">{t('nativeRetrieval.loading')}</p> : null}
      {model.sourceState === 'changed' ? (
        <p role="alert">{t('nativeRetrieval.sourceChanged')}</p>
      ) : null}
      {model.sourceState === 'unavailable' ? (
        <p role="alert">{t('nativeRetrieval.sourceUnavailable')}</p>
      ) : null}
      {model.source ? (
        <article>
          <h3>{model.source.title}</h3>
          <p>
            {t('nativeRetrieval.sourceRevision')}: {model.source.version}
          </p>
          <pre>{model.source.content}</pre>
        </article>
      ) : null}
    </>
  );
}
