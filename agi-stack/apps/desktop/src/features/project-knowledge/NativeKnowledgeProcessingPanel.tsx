import { useI18n } from '../../i18n';
import type {
  NativeKnowledgeProcessingController,
  NativeKnowledgeProcessingModel,
} from './nativeKnowledgeProcessingController';

export function NativeKnowledgeProcessingPanel({
  model,
  controller,
  disabled = false,
}: Readonly<{
  model: NativeKnowledgeProcessingModel;
  controller: NativeKnowledgeProcessingController;
  disabled?: boolean;
}>) {
  const { t } = useI18n();
  const operations = ['index_one', 'promote_index', 'select_embedding', 'retry_index'] as const;
  if (
    ![...operations, 'configure_embedding', 'process_one'].some((operation) =>
      model.allowedActions.includes(operation),
    )
  )
    return null;
  const busy = model.phase === 'loading' || model.phase === 'executing';
  const locked = busy || model.recoveryRequired || model.phase === 'unavailable';
  const receipt =
    model.outcome?.operation === 'index_one'
      ? model.outcome.result.receipt
      : model.failedTask?.receipt;
  return (
    <fieldset className="native-knowledge-processing" disabled={disabled}>
      <legend>{t('nativeProcessing.title')}</legend>
      <p>{t('nativeProcessing.explicitOnly')}</p>
      {model.phase === 'unavailable' ? (
        <p role="status">{t('nativeProcessing.unavailable')}</p>
      ) : (
        <>
          <button type="button" disabled={busy} onClick={() => void controller.refresh()}>
            {t('nativeProcessing.refresh')}
          </button>
          <div className="native-knowledge-processing-actions">
            {operations
              .filter((operation) => model.allowedActions.includes(operation))
              .map((operation) => (
                <button
                  key={operation}
                  type="button"
                  disabled={locked || (operation === 'retry_index' && !model.failedTask)}
                  onClick={() => void controller.review(operation)}
                >
                  {t(`nativeProcessing.${operation}`)}
                </button>
              ))}
          </div>
        </>
      )}
      {model.allowedActions.includes('configure_embedding') ? (
        <p>{t('nativeProcessing.providerContextUnavailable')}</p>
      ) : null}
      {model.allowedActions.includes('process_one') ? (
        <p>{t('nativeProcessing.workspaceContextUnavailable')}</p>
      ) : null}
      {model.snapshot ? (
        <dl>
          <dt>{t('nativeRetrieval.desired')}</dt>
          <dd>{model.snapshot.configuration?.build_id ?? t('nativeRetrieval.noConfiguration')}</dd>
          <dt>{t('nativeRetrieval.configRevision')}</dt>
          <dd>{model.snapshot.configuration?.revision ?? '—'}</dd>
          <dt>{t('nativeRetrieval.activeBuild')}</dt>
          <dd>{model.snapshot.active_build_id ?? t('nativeRetrieval.noActiveBuild')}</dd>
        </dl>
      ) : null}
      {model.selection ? (
        <section aria-label={t('nativeProcessing.review')}>
          <h3>{t('nativeProcessing.review')}</h3>
          <p>{t(`nativeProcessing.${model.selection.operation}Help`)}</p>
          <dl>
            <dt>{t('nativeProcessing.targetBuild')}</dt>
            <dd>{model.selection.build_id}</dd>
          </dl>
          <button type="button" disabled={busy} onClick={() => void controller.confirm()}>
            {t('nativeProcessing.confirm')}
          </button>
          <button type="button" disabled={busy} onClick={controller.cancelReview}>
            {t('common.cancel')}
          </button>
        </section>
      ) : null}
      {receipt ? (
        <section aria-label={t('nativeProcessing.taskReceipt')}>
          <h3>{t('nativeProcessing.taskReceipt')}</h3>
          <dl>
            <dt>{t('nativeRetrieval.source')}</dt>
            <dd>{receipt.input.source.memory_id}</dd>
            <dt>{t('nativeRetrieval.sourceRevision')}</dt>
            <dd>{receipt.input.source.revision}</dd>
            <dt>{t('nativeProcessing.attempt')}</dt>
            <dd>{receipt.attempt}</dd>
            <dt>{t('nativeProcessing.taskStatus')}</dt>
            <dd>{t(`nativeProcessing.status.${receipt.status}`)}</dd>
            {receipt.failure ? (
              <>
                <dt>{t('nativeProcessing.failure')}</dt>
                <dd>{t(`nativeProcessing.failure.${receipt.failure}`)}</dd>
              </>
            ) : null}
          </dl>
        </section>
      ) : null}
      {model.outcome?.operation === 'index_one' && model.outcome.result.receipt === null ? (
        <p role="status">{t('nativeProcessing.noTask')}</p>
      ) : null}
      {model.outcome?.operation === 'retry_index' ? (
        <p role="status">{t('nativeProcessing.queued')}</p>
      ) : null}
      {model.outcome?.operation === 'promote_index' ? (
        <p role="status">{t('nativeProcessing.promoted')}</p>
      ) : null}
      {model.outcome?.operation === 'select_embedding' ? (
        <p role="status">{t('nativeProcessing.selected')}</p>
      ) : null}
      {busy ? <p role="status">{t('nativeProcessing.working')}</p> : null}
      {model.recoveryRequired ? <p role="alert">{t('nativeProcessing.uncertain')}</p> : null}
      {model.notice ? <p role="status">{t(`nativeProcessing.${model.notice}`)}</p> : null}
      {model.error ? <p role="alert">{t(`nativeProcessing.${model.error}`)}</p> : null}
    </fieldset>
  );
}
