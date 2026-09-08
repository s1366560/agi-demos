import { useI18n } from '../../i18n';
import type {
  DiagnosticIndexSelection,
  NativeKnowledgeDiagnosticsController,
  NativeKnowledgeDiagnosticsModel,
} from './nativeKnowledgeDiagnosticsController';

export function NativeKnowledgeDiagnosticsPanel({
  model,
  controller,
  onSelectIndexFailure,
  disabled = false,
}: Readonly<{
  model: NativeKnowledgeDiagnosticsModel;
  controller: NativeKnowledgeDiagnosticsController;
  onSelectIndexFailure?: (selection: DiagnosticIndexSelection) => void | Promise<void>;
  disabled?: boolean;
}>) {
  const { t } = useI18n();
  if (model.phase === 'unavailable') return null;
  const busy = model.phase === 'loading';
  const page = model.mode === 'failed_processing' ? model.processing : model.index;
  return (
    <fieldset disabled={disabled || busy} className="native-knowledge-diagnostics">
      <legend>{t('nativeDiagnostics.title')}</legend>
      <p>{t('nativeDiagnostics.live')}</p>
      {(['failed_processing', 'failed_index'] as const)
        .filter((mode) => model.allowedActions.includes(mode))
        .map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={model.mode === mode}
            onClick={() => void controller.refresh(mode)}
          >
            {t(`nativeDiagnostics.${mode}`)}
          </button>
        ))}
      <button type="button" onClick={() => void controller.refresh()}>
        {t('nativeDiagnostics.refresh')}
      </button>
      {busy ? <p role="status">{t('nativeDiagnostics.loading')}</p> : null}
      {model.error ? <p role="alert">{t(`nativeDiagnostics.${model.error}`)}</p> : null}
      {model.configuration && model.mode === 'failed_index' ? (
        <p>
          {model.configuration.build_id} · {model.configuration.revision}
        </p>
      ) : null}
      {page?.items.length === 0 ? <p>{t('nativeDiagnostics.empty')}</p> : null}
      <ol>
        {page?.items.map((item, position) => {
          const source = 'source' in item ? item.source : item.input.source;
          return (
            <li key={`${source.change_sequence}:${item.attempt}`}>
              <p>
                {source.memory_id} · {t('nativeDiagnostics.revision')} {source.revision} ·{' '}
                {t('nativeDiagnostics.attempt')} {item.attempt}
              </p>
              <p>{t(`nativeProcessing.failure.${item.failure}`)}</p>
              {model.allowedActions.includes('processing_audits') ? (
                <button type="button" onClick={() => void controller.inspect(source)}>
                  {t('nativeDiagnostics.inspect')}
                </button>
              ) : null}
              {'input' in item &&
              onSelectIndexFailure &&
              model.allowedActions.includes('retry_index') ? (
                <button
                  type="button"
                  onClick={() => {
                    const selection = controller.selection(position);
                    if (selection) void onSelectIndexFailure(selection);
                  }}
                >
                  {t('nativeDiagnostics.select')}
                </button>
              ) : null}
            </li>
          );
        })}
      </ol>
      {page?.next_cursor ? (
        <button type="button" onClick={() => void controller.next()}>
          {t('nativeDiagnostics.next')}
        </button>
      ) : null}
      {model.audits ? (
        <section aria-label={t('nativeDiagnostics.audit')}>
          <h3>
            {t('nativeDiagnostics.audit')} · {model.auditSource?.memory_id}
          </h3>
          {model.audits.items.length === 0 ? <p>{t('nativeDiagnostics.noAudit')}</p> : null}
          <ol>
            {model.audits.items.map((item) => (
              <li key={item.attempt}>
                <p>
                  {t('nativeDiagnostics.attempt')} {item.attempt} ·{' '}
                  {t(`nativeDiagnostics.${item.status === 'failed' ? 'auditFailed' : item.status}`)}
                </p>
                <p>
                  {item.agent_id} · {item.provider_id} · {item.model_id} · {item.tool_name}
                </p>
                <p>
                  {t('nativeDiagnostics.started')} {item.started_at_ms} ·{' '}
                  {t('nativeDiagnostics.latency')} {item.latency_ms ?? '—'}
                </p>
                {item.failure ? <p>{t(`nativeProcessing.failure.${item.failure}`)}</p> : null}
              </li>
            ))}
          </ol>
          {model.audits.next_cursor && model.auditSource ? (
            <button type="button" onClick={() => void controller.inspect(model.auditSource!, true)}>
              {t('nativeDiagnostics.next')}
            </button>
          ) : null}
        </section>
      ) : null}
    </fieldset>
  );
}
