import { useI18n } from '../../i18n';
import type {
  NativeKnowledgeRetrievalController,
  NativeKnowledgeRetrievalModel,
} from './nativeKnowledgeRetrievalController';

export function NativeKnowledgeConfigurationPanel({
  model,
  controller,
  disabled = false,
  diagnosticsAvailable = false,
}: Readonly<{
  model: NativeKnowledgeRetrievalModel;
  controller: NativeKnowledgeRetrievalController;
  disabled?: boolean;
  diagnosticsAvailable?: boolean;
}>) {
  const { t } = useI18n();
  if (!model.allowedActions.includes('configuration')) return null;
  const snapshot = model.configuration;
  const configuration = snapshot?.configuration;
  return (
    <fieldset className="native-knowledge-configuration" disabled={disabled}>
      <legend>{t('nativeRetrieval.configuration')}</legend>
      <button
        type="button"
        disabled={model.phase === 'loading'}
        onClick={() => void controller.refreshConfiguration()}
      >
        {t('common.refresh')}
      </button>
      <h3>{t('nativeRetrieval.desired')}</h3>
      {configuration ? (
        <dl>
          <dt>{t('nativeRetrieval.configRevision')}</dt>
          <dd>{configuration.revision}</dd>
          <dt>{t('nativeRetrieval.build')}</dt>
          <dd>{configuration.build_id}</dd>
          <dt>{t('nativeRetrieval.provider')}</dt>
          <dd>{configuration.provider_id}</dd>
          <dt>{t('nativeRetrieval.providerRevision')}</dt>
          <dd>{configuration.provider_revision}</dd>
          <dt>{t('nativeRetrieval.model')}</dt>
          <dd>{configuration.model_id}</dd>
          <dt>{t('nativeRetrieval.dimensions')}</dt>
          <dd>{configuration.dimensions}</dd>
        </dl>
      ) : snapshot ? (
        <p>{t('nativeRetrieval.noConfiguration')}</p>
      ) : null}
      {snapshot ? (
        <>
          <h3>{t('nativeRetrieval.activeBuild')}</h3>
          <p>{snapshot.active_build_id ?? t('nativeRetrieval.noActiveBuild')}</p>
          <table>
            <caption>{t('nativeRetrieval.processingCoverage')}</caption>
            <tbody>
              <tr>
                <th scope="row">{t('nativeRetrieval.rawSources')}</th>
                <td>{snapshot.processing.current_sources}</td>
              </tr>
              <tr>
                <th scope="row">{t('nativeRetrieval.appliedSources')}</th>
                <td>{snapshot.processing.applied_sources}</td>
              </tr>
              <tr>
                <th scope="row">{t('nativeRetrieval.pendingSources')}</th>
                <td>{snapshot.processing.pending_sources}</td>
              </tr>
              <tr>
                <th scope="row">{t('nativeRetrieval.failedProcessing')}</th>
                <td>{snapshot.processing.failed_sources}</td>
              </tr>
            </tbody>
          </table>
          <h3>{t('nativeRetrieval.indexCoverage')}</h3>
          {snapshot.index ? (
            <>
              <table>
                <tbody>
                  <tr>
                    <th scope="row">{t('nativeRetrieval.indexSources')}</th>
                    <td>{snapshot.index.current_sources}</td>
                  </tr>
                  <tr>
                    <th scope="row">{t('nativeRetrieval.indexedSources')}</th>
                    <td>{snapshot.index.completed_sources}</td>
                  </tr>
                  <tr>
                    <th scope="row">{t('nativeRetrieval.failedIndex')}</th>
                    <td>{snapshot.index.failed_sources}</td>
                  </tr>
                </tbody>
              </table>
              <p>
                {snapshot.index.current_sources > 0
                  ? `${snapshot.index.completed_sources} / ${snapshot.index.current_sources} (${((snapshot.index.completed_sources / snapshot.index.current_sources) * 100).toFixed(1)}%)`
                  : t('nativeRetrieval.noDenominator')}
              </p>
            </>
          ) : (
            <p>{t('nativeRetrieval.noCoverage')}</p>
          )}
          <p>{t('nativeRetrieval.coverageHelp')}</p>
          {!diagnosticsAvailable &&
          (snapshot.processing.failed_sources > 0 || (snapshot.index?.failed_sources ?? 0) > 0) ? (
            <p>{t('nativeRetrieval.failureDetailsUnavailable')}</p>
          ) : null}
        </>
      ) : null}
      {!model.mode && model.phase === 'loading' ? (
        <p role="status">{t('nativeRetrieval.loading')}</p>
      ) : null}
      {!model.mode && model.error ? (
        <p role="alert">{t(`nativeRetrieval.${model.error}`)}</p>
      ) : null}
    </fieldset>
  );
}
