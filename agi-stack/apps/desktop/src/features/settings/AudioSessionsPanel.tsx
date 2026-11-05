import { useEffect, useRef, useState } from 'react';
import type { AudioSession, AudioSessionOperation, AudioSessionsClient, AudioSessionsSnapshot } from '../../api/audioSessionsClient';
import { useI18n } from '../../i18n';
import './AudioSessionsPanel.css';

export function AudioSessionsPanel({ client }: { client: AudioSessionsClient | null }) {
  const { t } = useI18n();
  const [snapshot, setSnapshot] = useState<AudioSessionsSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [source, setSource] = useState<AudioSession['source']>('mixed');
  const [profile, setProfile] = useState('');
  const [appId, setAppId] = useState('');
  const [token, setToken] = useState('');
  const activeClient = useRef(client);
  activeClient.current = client;
  const sequence = useRef(0);
  useEffect(() => {
    setSnapshot(null); setProfile(''); setToken(''); setError(false);
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      if (!client) return;
      const current = sequence.current;
      try {
        const value = await client.manage({ action: 'list' }, controller.signal);
        if (!controller.signal.aborted && current === sequence.current) { setSnapshot(value); setError(false); }
      } catch { if (!controller.signal.aborted && current === sequence.current) setError(true); }
      if (!controller.signal.aborted) timer = setTimeout(() => void refresh(), 2000);
    };
    void refresh();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [client]);
  const manage = async (operation: AudioSessionOperation) => {
    if (!client || busy) return;
    sequence.current += 1;
    setBusy(true); setError(false);
    try {
      const value = await client.manage(operation);
      if (activeClient.current === client) setSnapshot(value);
    } catch { if (activeClient.current === client) setError(true); }
    finally { if (activeClient.current === client) { setBusy(false); sequence.current += 1; } }
  };
  return <section className="audio-sessions-panel" aria-label={t('audio.title')}>
    <header><h4>{t('audio.title')}</h4><p>{t('audio.description')}</p></header>
    <p className="audio-session-private">{t('audio.private')}</p>
    <div className="audio-session-controls">
      <label>{t('audio.source')}<select value={source} onChange={event => setSource(event.target.value as AudioSession['source'])}>
        {(['mixed', 'microphone', 'system'] as const).map(value => <option key={value} value={value}>{t(`cua.recording.source.${value}`)}</option>)}
      </select></label>
      <label>{t('audio.provider')}<select value={profile} onChange={event => setProfile(event.target.value)}>
        <option value="">{t('audio.recordOnly')}</option>
        {snapshot?.profiles.map(value => <option key={value.id} value={value.id}>{value.name}</option>)}
      </select></label>
      <button disabled={!snapshot || busy} onClick={() => void manage({ action: 'start', source, max_duration_ms: 28_800_000, ...(profile ? { provider_profile_id: profile } : {}) })}>{t('audio.start')}</button>
    </div>
    <details><summary>{t('audio.configure')}</summary>
      <form onSubmit={event => { event.preventDefault(); const access_token = token; setToken(''); void manage({ action: 'configure_provider', name: 'Volcengine Speech', app_id: appId, access_token }); }}>
        <label>{t('audio.appId')}<input value={appId} onChange={event => setAppId(event.target.value)} autoComplete="off" /></label>
        <label>{t('audio.token')}<input type="password" value={token} onChange={event => setToken(event.target.value)} autoComplete="off" /></label>
        <button disabled={busy || !appId.trim() || !token}>{t('audio.saveProfile')}</button>
      </form>
    </details>
    {error ? <p role="alert">{t('audio.failed')}</p> : null}
    {snapshot?.sessions.map(session => <article key={session.audio_session_id} className="audio-session-card">
      <header><strong>{new Date(session.started_at).toLocaleString()}</strong><span role="status">{t(`audio.state.${session.state}`)}</span></header>
      <p>{Math.floor(session.captured_ms / 60_000)}:{String(Math.floor(session.captured_ms / 1000) % 60).padStart(2, '0')} · {t('audio.segments', { count: session.segments.length })}</p>
      <div className="audio-session-actions">
        {session.state === 'recording' ? <button disabled={busy} onClick={() => void manage({ action: 'pause', audio_session_id: session.audio_session_id, generation: session.generation })}>{t('audio.pause')}</button> : null}
        {session.state === 'paused' || session.state === 'interrupted' ? <button disabled={busy} onClick={() => void manage({ action: 'resume', audio_session_id: session.audio_session_id, generation: session.generation })}>{t('audio.resume')}</button> : null}
        {['recording', 'paused', 'interrupted'].includes(session.state) ? <button disabled={busy} onClick={() => void manage({ action: 'stop', audio_session_id: session.audio_session_id, generation: session.generation })}>{t('audio.stop')}</button> : null}
      </div>
      {session.error_code ? <p role="alert">{t('audio.failed')} <code>{session.error_code}</code></p> : null}
      <details open={session.transcript.length > 0}><summary>{t('audio.transcript')}</summary>
        {session.transcript.length ? <ol className="audio-transcript">{session.transcript.map(segment => <li key={segment.segment_id}><time>{Math.floor((segment.start_ms ?? 0) / 1000)}s</time><span>{segment.speaker_id ?? ''}</span><p>{segment.text}</p></li>)}</ol> : <p>{t('audio.emptyTranscript')}</p>}
      </details>
      {session.summary ? <section><h5>{t('audio.summary')}</h5><p>{session.summary.text}</p></section> : null}
    </article>)}
  </section>;
}
