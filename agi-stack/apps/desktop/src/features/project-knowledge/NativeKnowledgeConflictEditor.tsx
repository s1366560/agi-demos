import { useI18n } from '../../i18n';
import type { NativeKnowledgeCloudContext } from './nativeKnowledgeContracts';
import type {
  NativeKnowledgeConflictController,
  NativeKnowledgeConflictModel,
} from './nativeKnowledgeConflictController';

export function NativeKnowledgeConflictEditor({
  model,
  controller,
  disabled = false,
}: Readonly<{
  model: NativeKnowledgeConflictModel;
  controller: NativeKnowledgeConflictController;
  disabled?: boolean;
}>) {
  const { t } = useI18n();
  if (model.phase === 'idle') return null;
  const locked = ['loading', 'checking', 'saving', 'uncertain'].includes(model.phase);
  const context = model.context;
  const cloud =
    context && 'original_request' in context ? (context as NativeKnowledgeCloudContext) : null;
  const resume =
    model.selection?.kind === 'resolution' &&
    model.record &&
    !model.record.receipt &&
    !model.record.rejection &&
    model.allowedActions.includes('resume_resolution');
  return (
    <fieldset className="native-knowledge-conflict" disabled={disabled}>
      <legend>{t('nativeSync.conflictReview')}</legend>
      {model.error ? <p role="alert">{t(`nativeSync.${model.error}`)}</p> : null}
      {['loading', 'checking', 'saving'].includes(model.phase) ? (
        <p role="status">{t('nativeSync.working')}</p>
      ) : null}
      {context ? (
        <>
          <p>{context.memory_id}</p>
          <div className="native-knowledge-comparison">
            <section>
              <h3>{t('nativeSync.local')}</h3>
              <p>
                {t('nativeMemories.version')}: {context.local.version}
              </p>
              {context.local_deleted ? <p>{t('nativeSync.deleted')}</p> : null}
              <h4>{context.local.title}</h4>
              <pre>{context.local.content}</pre>
              <details>
                <summary>{t('nativeSync.metadata')}</summary>
                <pre>
                  {JSON.stringify({ ...context.local, metadata: context.local_metadata }, null, 2)}
                </pre>
              </details>
            </section>
            <section>
              <h3>{t('nativeSync.baseline')}</h3>
              {context.baseline ? (
                <>
                  <p>
                    {t('nativeMemories.version')}: {context.baseline.revision}
                  </p>
                  {context.baseline.deleted ? <p>{t('nativeSync.deleted')}</p> : null}
                  <h4>{context.baseline.content.title}</h4>
                  <pre>{context.baseline.content.content}</pre>
                  <details>
                    <summary>{t('nativeSync.metadata')}</summary>
                    <pre>{JSON.stringify(context.baseline, null, 2)}</pre>
                  </details>
                </>
              ) : (
                <p>{t('nativeSync.absent')}</p>
              )}
            </section>
            <section>
              <h3>{t('nativeSync.remote')}</h3>
              {context.remote ? (
                <>
                  <p>
                    {t('nativeMemories.version')}: {context.remote.revision}
                  </p>
                  {context.remote.deleted ? <p>{t('nativeSync.deleted')}</p> : null}
                  <h4>{context.remote.content.title}</h4>
                  <pre>{context.remote.content.content}</pre>
                  <details>
                    <summary>{t('nativeSync.metadata')}</summary>
                    <pre>{JSON.stringify(context.remote, null, 2)}</pre>
                  </details>
                </>
              ) : (
                <p>{t('nativeSync.absent')}</p>
              )}
            </section>
            {cloud ? (
              <section>
                <h3>{t('nativeSync.originalProposal')}</h3>
                <p>{t('nativeSync.originalProposalHelp')}</p>
                <pre>{JSON.stringify(cloud.original_request, null, 2)}</pre>
              </section>
            ) : null}
          </div>
        </>
      ) : null}
      {model.record ? (
        <details>
          <summary>{t('nativeSync.resolutionRecord')}</summary>
          <pre>{JSON.stringify(model.record, null, 2)}</pre>
        </details>
      ) : null}
      {model.phase === 'reviewing' ? (
        <div className="native-knowledge-actions">
          {controller.decisions().map((decision) => (
            <button
              key={decision}
              type="button"
              aria-pressed={model.decision === decision}
              onClick={() => controller.choose(decision)}
            >
              {t(`nativeSync.${decision}`)}
            </button>
          ))}
        </div>
      ) : null}
      {model.draft ? (
        <div className="native-memory-editor__fields">
          <label>
            {t('nativeMemories.titleLabel')}
            <input
              value={model.draft.title}
              readOnly={locked}
              onChange={(event) => controller.setDraft({ title: event.target.value })}
            />
          </label>
          <label>
            {t('nativeMemories.contentLabel')}
            <textarea
              value={model.draft.content}
              readOnly={locked}
              onChange={(event) => controller.setDraft({ content: event.target.value })}
            />
          </label>
          <details>
            <summary>{t('nativeSync.preservedMetadata')}</summary>
            <pre>
              {JSON.stringify({ ...model.draft, title: undefined, content: undefined }, null, 2)}
            </pre>
          </details>
        </div>
      ) : null}
      {model.phase === 'accepted' ? (
        <p role="status">
          {t(
            model.pendingReconciliation
              ? 'nativeSync.pendingReconciliation'
              : 'nativeSync.accepted',
          )}
        </p>
      ) : null}
      <div className="native-knowledge-actions">
        {model.phase === 'reviewing' && (model.decision || resume) ? (
          <button type="button" onClick={() => void controller.submit()}>
            {t(resume ? 'nativeSync.resume' : 'nativeSync.confirm')}
          </button>
        ) : null}
        {model.phase === 'uncertain' ? (
          <button type="button" onClick={() => void controller.retry()}>
            {t('nativeMemories.retryWrite')}
          </button>
        ) : null}
        {model.phase === 'error' || model.phase === 'accepted' ? (
          <button
            type="button"
            disabled={!model.selection}
            onClick={() => void controller.reload()}
          >
            {t('common.refresh')}
          </button>
        ) : null}
        <button type="button" disabled={locked} onClick={controller.close}>
          {t('common.close')}
        </button>
      </div>
    </fieldset>
  );
}
