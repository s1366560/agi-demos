import { useI18n } from '../../i18n';
import type {
  NativeKnowledgeProcessingController,
  NativeKnowledgeProcessingModel,
} from './nativeKnowledgeProcessingController';

export function NativeKnowledgeProcessingChoices({
  model,
  controller,
  locked,
}: Readonly<{
  model: NativeKnowledgeProcessingModel;
  controller: NativeKnowledgeProcessingController;
  locked: boolean;
}>) {
  const { t } = useI18n();
  return (
    <>
      {(['configure_embedding', 'process_one'] as const)
        .filter((operation) => model.allowedActions.includes(operation))
        .map((operation) => (
          <section key={operation}>
            {!model.inputsAvailable ? (
              <p>
                {t(
                  operation === 'configure_embedding'
                    ? 'nativeProcessing.providerContextUnavailable'
                    : 'nativeProcessing.workspaceContextUnavailable',
                )}
              </p>
            ) : (
              <>
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => void controller.prepareInputs(operation)}
                >
                  {t(`nativeProcessing.choose.${operation}`)}
                </button>
                {model.inputOperation === operation && model.inputs ? (
                  <>
                    {operation === 'configure_embedding' ? (
                      <>
                        <label>
                          {t('nativeProcessing.embeddingModel')}
                          <select
                            disabled={locked}
                            value={
                              model.embeddingChoice
                                ? JSON.stringify([
                                    model.embeddingChoice.providerId,
                                    model.embeddingChoice.modelId,
                                  ])
                                : ''
                            }
                            onChange={(event) => {
                              const item = model.inputs!.embeddingModels.items.find(
                                (choice) =>
                                  JSON.stringify([choice.providerId, choice.modelId]) ===
                                  event.target.value,
                              );
                              controller.chooseEmbedding(
                                item?.providerId ?? '',
                                item?.modelId ?? '',
                              );
                            }}
                          >
                            <option value="">{t('nativeProcessing.chooseOne')}</option>
                            {model.inputs.embeddingModels.items.map((item) => (
                              <option
                                key={JSON.stringify([item.providerId, item.modelId])}
                                value={JSON.stringify([item.providerId, item.modelId])}
                              >
                                {item.providerName} · {item.modelId} ·{' '}
                                {t('nativeProcessing.providerRevision')} {item.providerRevision}
                              </option>
                            ))}
                          </select>
                        </label>
                        {model.inputs.embeddingModels.availability === 'unavailable' ? (
                          <p role="status">{t('nativeProcessing.providerContextUnavailable')}</p>
                        ) : model.inputs.embeddingModels.items.length === 0 ? (
                          <p role="status">{t('nativeProcessing.noModels')}</p>
                        ) : null}
                      </>
                    ) : (
                      <>
                        <label>
                          {t('nativeProcessing.workspace')}
                          <select
                            disabled={locked}
                            value={model.workspaceChoice?.id ?? ''}
                            onChange={(event) => controller.chooseWorkspace(event.target.value)}
                          >
                            <option value="">{t('nativeProcessing.chooseOne')}</option>
                            {model.inputs.workspaces.items.map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        {model.inputs.workspaces.availability === 'unavailable' ? (
                          <p role="status">{t('nativeProcessing.workspaceContextUnavailable')}</p>
                        ) : model.inputs.workspaces.items.length === 0 ? (
                          <p role="status">{t('nativeProcessing.noWorkspaces')}</p>
                        ) : null}
                      </>
                    )}
                    <button
                      type="button"
                      disabled={
                        locked ||
                        !(operation === 'configure_embedding'
                          ? model.embeddingChoice
                          : model.workspaceChoice)
                      }
                      onClick={() => void controller.review(operation)}
                    >
                      {t(`nativeProcessing.${operation}`)}
                    </button>
                  </>
                ) : null}
              </>
            )}
          </section>
        ))}
    </>
  );
}
