import { useEffect, useState } from 'react';
import type {
  ComputerUseClientV2,
  ComputerUseOperation,
  ComputerUseRecording,
} from '../../api/computerUseClientV2';
import { computerUseTimestamp } from '../../api/computerUseTime';
import {
  computerUseRecordingDuration,
  computerUseRecordingEndReasonKey,
} from '../../api/computerUseRecording';
import { useI18n } from '../../i18n';
import { ComputerUseAudio } from './ComputerUseAudio';

type Props = {
  recordings: readonly ComputerUseRecording[];
  client: ComputerUseClientV2 | null;
  stopping: boolean;
  manage: (operation: ComputerUseOperation) => Promise<void>;
};

export function ComputerUseRecordings(props: Props) {
  const { t } = useI18n();
  const active = props.recordings.some((recording) => recording.status === 'recording');
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  if (!props.recordings.length) return null;
  return (
    <section className="computer-use-recordings" aria-label={t('cua.recordings')}>
      <h4>{t('cua.recordings')}</h4>
      {props.recordings.map((recording) => (
        <Recording key={recording.recording_id} {...props} recording={recording} now={now} />
      ))}
    </section>
  );
}

function Recording({
  recording,
  now,
  client,
  manage,
  stopping,
}: Props & {
  recording: ComputerUseRecording;
  now: number;
}) {
  const { t } = useI18n();
  const [pending, setPending] = useState(false);
  const status = pending
    ? recording.status === 'recording'
      ? 'stopping'
      : 'pending_export'
    : recording.status;
  const started = computerUseTimestamp(recording.started_at);
  const duration = computerUseRecordingDuration(recording, now);
  const stop = async () => {
    if (pending || stopping) return;
    setPending(true);
    try {
      await manage({
        action: 'audio_stop',
        session_id: recording.session_id,
        recording_id: recording.recording_id,
      });
    } finally {
      setPending(false);
    }
  };
  return (
    <article className="computer-use-recording" data-recording-status={status}>
      <strong>{t(`cua.recording.source.${recording.source}`)}</strong>
      <span role="status">{t(`cua.recording.status.${status}`)}</span>
      <span aria-label={t('session.elapsed')}>{duration}</span>
      {started ? <time dateTime={started}>{new Date(started).toLocaleTimeString()}</time> : null}
      {recording.status === 'recording' || recording.can_retry_export === true ? (
        <button type="button" disabled={stopping || pending} onClick={() => void stop()}>
          {t(recording.status === 'recording' ? 'cua.recording.stop' : 'cua.recording.retrySave')}
        </button>
      ) : null}
      {recording.end_reason ? (
        <span>{t(computerUseRecordingEndReasonKey(recording.end_reason))}</span>
      ) : null}
      {recording.partial ? <p>{t('cua.recording.partial')}</p> : null}
      {recording.status === 'failed' || recording.error_code ? (
        <p role="alert">
          {t(
            recording.error_code === 'cua_audio_source_missing'
              ? 'cua.recording.sourceMissing'
              : recording.can_retry_export
                ? 'cua.recording.exportFailed'
                : 'cua.recording.captureFailed',
          )}
        </p>
      ) : null}
      {recording.error_code ? (
        <details>
          <summary>{t('cua.recording.details')}</summary>
          <code>{recording.error_code}</code>
        </details>
      ) : null}
      {recording.artifacts.map((artifact) => (
        <ComputerUseAudio
          key={artifact.artifact_id}
          client={client}
          artifactId={artifact.artifact_id}
          label={t(`cua.recording.source.${artifact.source ?? recording.source}`)}
        />
      ))}
    </article>
  );
}
