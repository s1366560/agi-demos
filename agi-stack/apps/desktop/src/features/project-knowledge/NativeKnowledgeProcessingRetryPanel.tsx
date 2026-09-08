import { useI18n } from '../../i18n';
import type {
  NativeKnowledgeProcessingRetryController,
  NativeKnowledgeProcessingRetryModel,
} from './nativeKnowledgeProcessingRetryController';

export function NativeKnowledgeProcessingRetryPanel({
  model,
  controller,
  disabled = false,
}: Readonly<{
  model: NativeKnowledgeProcessingRetryModel;
  controller: NativeKnowledgeProcessingRetryController;
  disabled?: boolean;
}>) {
  const { t } = useI18n();
  if (model.phase === 'unavailable' || (model.phase === 'idle' && !model.snapshot && !model.error))
    return null;
  const busy = model.phase === 'loading' || model.phase === 'executing';
  const source = model.selection?.failure.source ?? model.snapshot?.source;
  return (
    <fieldset disabled={disabled || busy}>
      <legend>{t('nativeProcessingRetry.title')}</legend>
      <p>{t('nativeProcessingRetry.explanation')}</p>
      {source ? (
        <p>
          {source.memory_id} · {t('nativeDiagnostics.revision')} {source.revision} ·{' '}
          {t('nativeProcessingRetry.sequence')} {source.change_sequence}
        </p>
      ) : null}
      {model.selection ? (
        <p>
          {t('nativeDiagnostics.attempt')} {model.selection.failure.attempt} ·{' '}
          {t(`nativeProcessing.failure.${model.selection.failure.failure}`)}
        </p>
      ) : null}
      {busy ? <p role="status">{t('nativeProcessingRetry.checking')}</p> : null}
      {model.error ? <p role="alert">{t(`nativeProcessingRetry.${model.error}`)}</p> : null}
      {model.phase === 'selected' ? (
        <button type="button" onClick={() => void controller.review()}>
          {t('nativeProcessingRetry.review')}
        </button>
      ) : null}
      {model.phase === 'reviewing' ? (
        <button type="button" onClick={() => void controller.confirm()}>
          {t('nativeProcessingRetry.confirm')}
        </button>
      ) : null}
      {model.phase === 'selected' || model.phase === 'reviewing' ? (
        <button type="button" onClick={controller.cancel}>
          {t('nativeProcessingRetry.cancel')}
        </button>
      ) : null}
      {model.phase === 'accepted' ? (
        <p role="status">{t('nativeProcessingRetry.accepted')}</p>
      ) : null}
      {model.recoveryRequired ? (
        <>
          <p role="alert">{t('nativeProcessingRetry.unknown')}</p>
          <button type="button" onClick={() => void controller.recover()}>
            {t('nativeProcessingRetry.recover')}
          </button>
        </>
      ) : null}
      {model.recoveredUnknown ? (
        <>
          <p role="status">{t('nativeProcessingRetry.recovered')}</p>
          <p>
            {model.snapshot?.current && model.snapshot.task
              ? t(`nativeProcessingRetry.state.${model.snapshot.task.state}`)
              : t('nativeProcessingRetry.obsolete')}
          </p>
        </>
      ) : null}
    </fieldset>
  );
}
