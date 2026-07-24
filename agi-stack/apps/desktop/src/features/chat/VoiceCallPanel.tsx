import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Cross2Icon,
  EnterFullScreenIcon,
  MinusIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  formatVoiceCallDuration,
  voiceCallFailureKey,
  type VoiceCallFailureCode,
  type VoiceCallStatus,
  type VoiceCallTranscript,
} from './voiceCallModel';

type VoiceCallPanelProps = {
  status: VoiceCallStatus;
  transcript: VoiceCallTranscript;
  errorCode: VoiceCallFailureCode | null;
  isMuted: boolean;
  isSpeaking: boolean;
  startedAt: number | null;
  onToggleMute: () => void;
  onEnd: () => void;
};

type PanelPosition = {
  x: number;
  y: number;
};

export function VoiceCallPanel({
  status,
  transcript,
  errorCode,
  isMuted,
  isSpeaking,
  startedAt,
  onToggleMute,
  onEnd,
}: VoiceCallPanelProps) {
  const { t } = useI18n();
  const [minimized, setMinimized] = useState(false);
  const [durationSeconds, setDurationSeconds] = useState(0);
  const [position, setPosition] = useState<PanelPosition>({ x: 24, y: 24 });
  const panelRef = useRef<HTMLElement>(null);
  const dragRef = useRef<{
    pointerId: number;
    offsetX: number;
    offsetY: number;
  } | null>(null);

  useEffect(() => {
    setPosition({
      x: Math.max(16, window.innerWidth - 408),
      y: Math.max(16, window.innerHeight - 500),
    });
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    if (status !== 'connected' || !startedAt) {
      setDurationSeconds(0);
      return;
    }
    const updateDuration = () => {
      setDurationSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1_000)));
    };
    updateDuration();
    const timer = window.setInterval(updateDuration, 1_000);
    return () => window.clearInterval(timer);
  }, [startedAt, status]);

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      setPosition({
        x: Math.max(0, Math.min(window.innerWidth - 120, event.clientX - drag.offsetX)),
        y: Math.max(0, Math.min(window.innerHeight - 64, event.clientY - drag.offsetY)),
      });
    };
    const finish = (event: PointerEvent) => {
      if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
    };
  }, []);

  const panelStatus =
    status === 'connecting'
      ? t('composer.voiceCall.connecting')
      : status === 'connected'
        ? isSpeaking
          ? t('composer.voiceCall.aiSpeaking')
          : t('composer.voiceCall.connected')
        : status === 'error'
          ? t('composer.voiceCall.error')
          : t('composer.voiceCall.ended');
  const startDrag = (event: React.PointerEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest('button')) return;
    dragRef.current = {
      pointerId: event.pointerId,
      offsetX: event.clientX - position.x,
      offsetY: event.clientY - position.y,
    };
  };

  const content = minimized ? (
    <section
      ref={panelRef}
      className="voice-call-panel is-minimized"
      style={{ transform: `translate(${position.x}px, ${position.y}px)` }}
      tabIndex={-1}
      aria-label={t('composer.voiceCall.region')}
      onPointerDown={startDrag}
    >
      <span
        className={`voice-call-presence${isSpeaking ? ' is-speaking' : ''}`}
        aria-hidden="true"
      />
      <span className="voice-call-minimized-status" aria-live="polite">
        <strong>{panelStatus}</strong>
        <small>{formatVoiceCallDuration(durationSeconds)}</small>
      </span>
      <button
        type="button"
        aria-label={t('composer.voiceCall.expand')}
        title={t('composer.voiceCall.expand')}
        onClick={() => setMinimized(false)}
      >
        <EnterFullScreenIcon aria-hidden="true" />
      </button>
      <button
        type="button"
        className="voice-call-end-button"
        aria-label={t('composer.voiceCall.end')}
        title={t('composer.voiceCall.end')}
        onClick={onEnd}
      >
        <Cross2Icon aria-hidden="true" />
      </button>
    </section>
  ) : (
    <section
      ref={panelRef}
      className="voice-call-panel"
      style={{ transform: `translate(${position.x}px, ${position.y}px)` }}
      tabIndex={-1}
      aria-label={t('composer.voiceCall.region')}
      onPointerDown={startDrag}
    >
      <header className="voice-call-header">
        <span>
          <strong>{t('composer.voiceCall.title')}</strong>
          <small aria-live="polite">{panelStatus}</small>
        </span>
        <span className="voice-call-header-actions">
          <time aria-label={t('composer.voiceCall.duration')}>
            {formatVoiceCallDuration(durationSeconds)}
          </time>
          <button
            type="button"
            aria-label={t('composer.voiceCall.minimize')}
            title={t('composer.voiceCall.minimize')}
            onClick={() => setMinimized(true)}
          >
            <MinusIcon aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label={t('composer.voiceCall.end')}
            title={t('composer.voiceCall.end')}
            onClick={onEnd}
          >
            <Cross2Icon aria-hidden="true" />
          </button>
        </span>
      </header>

      {errorCode ? (
        <div className="voice-call-error" role="alert">
          {t(voiceCallFailureKey(errorCode))}
        </div>
      ) : null}

      <div className={`voice-call-avatar${isSpeaking ? ' is-speaking' : ''}`}>
        <span aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </span>
        <strong>{isSpeaking ? t('composer.voiceCall.aiSpeaking') : panelStatus}</strong>
      </div>

      <div className="voice-call-transcript" aria-live="polite" aria-atomic="false">
        {transcript.asrFinal ? (
          <p className="voice-call-user-text">{transcript.asrFinal}</p>
        ) : null}
        {transcript.asrInterim ? (
          <p className="voice-call-interim-text">{transcript.asrInterim}</p>
        ) : null}
        {transcript.agentResponse ? (
          <p className="voice-call-agent-text">
            {transcript.agentResponse}
            {transcript.agentStreaming ? <span aria-hidden="true">|</span> : null}
          </p>
        ) : null}
        {!transcript.asrFinal &&
        !transcript.asrInterim &&
        !transcript.agentResponse &&
        !errorCode ? (
          <p className="voice-call-empty-text">{t('composer.voiceCall.listening')}</p>
        ) : null}
      </div>

      <footer className="voice-call-controls">
        <button
          type="button"
          className={isMuted ? 'is-active' : ''}
          aria-label={t(isMuted ? 'composer.voiceCall.unmute' : 'composer.voiceCall.mute')}
          aria-pressed={isMuted}
          title={t(isMuted ? 'composer.voiceCall.unmute' : 'composer.voiceCall.mute')}
          disabled={status !== 'connected'}
          onClick={onToggleMute}
        >
          <CallMicrophoneIcon muted={isMuted} />
        </button>
        <button
          type="button"
          className="voice-call-end-button"
          aria-label={t('composer.voiceCall.end')}
          title={t('composer.voiceCall.end')}
          onClick={onEnd}
        >
          <CallEndIcon />
        </button>
      </footer>
    </section>
  );

  return createPortal(content, document.body);
}

function CallEndIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
    >
      <path
        d="M5.2 15.2c3.8-3 9.8-3 13.6 0l-1.8 3-3.4-1.5v-2.2h-3.2v2.2L7 18.2l-1.8-3Z"
        fill="currentColor"
      />
    </svg>
  );
}

function CallMicrophoneIcon({ muted }: { muted: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      width="20"
      height="20"
      fill="none"
    >
      <rect
        x="7"
        y="2.5"
        width="6"
        height="9"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M4.8 9.5a5.2 5.2 0 0 0 10.4 0M10 14.7v2.8M7.5 17.5h5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      {muted ? (
        <path d="M3 4.5 17 15.5" stroke="currentColor" strokeWidth="1.6" />
      ) : null}
    </svg>
  );
}
