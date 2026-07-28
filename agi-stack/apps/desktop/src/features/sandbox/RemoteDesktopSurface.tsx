import { useCallback, useEffect, useRef, useState } from 'react';
import {
  EnterFullScreenIcon,
  ExitFullScreenIcon,
  ReloadIcon,
  SpeakerLoudIcon,
} from '@radix-ui/react-icons';
import { Badge, Button, Text } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type { SandboxRuntimeCapability } from './sandboxRuntimeClient';
import {
  remoteDesktopReconnectDelay,
  type RemoteDesktopResolution,
  type RemoteDesktopSession,
} from './sandboxRuntimeSurfaceClient';
import type { RemoteDesktopLoadStatus } from './useSandboxRuntimeSurface';
import './RemoteDesktopSurface.css';

type RemoteDesktopSurfaceProps = {
  capability: SandboxRuntimeCapability;
  session: RemoteDesktopSession | null;
  sessionRevision: number;
  status: RemoteDesktopLoadStatus;
  reasonCode: string | null;
  resolution: RemoteDesktopResolution;
  onResolutionChange: (resolution: RemoteDesktopResolution) => void;
  onStart: (resolution?: RemoteDesktopResolution) => Promise<void>;
  onReconnect: (resolution?: RemoteDesktopResolution) => Promise<void>;
};

const RESOLUTIONS: readonly RemoteDesktopResolution[] = [
  '1280x720',
  '1600x900',
  '1920x1080',
  '2560x1440',
];
const MAX_RECONNECT_ATTEMPTS = 10;

export function RemoteDesktopSurface({
  capability,
  session,
  sessionRevision,
  status,
  reasonCode,
  resolution,
  onResolutionChange,
  onStart,
  onReconnect,
}: RemoteDesktopSurfaceProps) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const retryAttemptRef = useRef(0);
  const [frameStatus, setFrameStatus] =
    useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [isFullscreen, setIsFullscreen] = useState(false);

  const exitFullscreen = useCallback(async () => {
    if (document.fullscreenElement) await document.exitFullscreen();
  }, []);

  const toggleFullscreen = useCallback(async () => {
    if (document.fullscreenElement) {
      await exitFullscreen();
      return;
    }
    await containerRef.current?.requestFullscreen();
  }, [exitFullscreen]);

  useEffect(() => {
    const onFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === containerRef.current);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && document.fullscreenElement) {
        void exitFullscreen();
      }
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('fullscreenchange', onFullscreenChange);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [exitFullscreen]);

  useEffect(() => {
    if (!session) {
      setFrameStatus('idle');
      return;
    }
    setFrameStatus('loading');
  }, [session, sessionRevision]);

  useEffect(() => {
    if (status !== 'error' && frameStatus !== 'error') return undefined;
    const attempt = retryAttemptRef.current;
    if (attempt >= MAX_RECONNECT_ATTEMPTS) return undefined;
    const delay = remoteDesktopReconnectDelay(attempt);
    retryAttemptRef.current = attempt + 1;
    const timer = window.setTimeout(() => {
      setFrameStatus('loading');
      void onReconnect();
    }, delay);
    return () => window.clearTimeout(timer);
  }, [frameStatus, onReconnect, status]);

  if (capability.availability !== 'available') {
    return (
      <section
        className="remote-desktop-surface remote-desktop-surface--unavailable"
        data-reason-code={capability.reason_code ?? 'kasm_proxy_contract_unavailable'}
      >
        <strong>{t('sandbox.remoteDesktopUnavailable')}</strong>
        <Text size="1" color="gray">
          {t('sandbox.remoteDesktopUnavailableDescription')}
        </Text>
        {capability.reason_code ? <code>{capability.reason_code}</code> : null}
      </section>
    );
  }

  const reconnect = () => {
    retryAttemptRef.current = 0;
    setFrameStatus('loading');
    void onReconnect();
  };

  const changeResolution = (nextResolution: RemoteDesktopResolution) => {
    onResolutionChange(nextResolution);
    if (session) {
      retryAttemptRef.current = 0;
      setFrameStatus('loading');
      void onReconnect(nextResolution);
    }
  };

  return (
    <section
      ref={containerRef}
      className="remote-desktop-surface"
      data-auth-mode={session?.descriptor.auth_mode ?? 'scoped_http_only_cookie'}
      data-frame-status={frameStatus}
    >
      <header className="remote-desktop-surface__toolbar">
        <span>
          <strong>{t('sandbox.remoteDesktopTitle')}</strong>
          <Badge
            color={
              status === 'ready' && frameStatus === 'ready'
                ? 'green'
                : status === 'error' || frameStatus === 'error'
                  ? 'red'
                  : 'amber'
            }
            variant="soft"
            role="status"
          >
            {status === 'ready' && frameStatus === 'ready'
              ? t('sandbox.remoteDesktopConnected')
              : status === 'starting' || frameStatus === 'loading'
                ? t('sandbox.remoteDesktopConnecting')
                : status === 'error' || frameStatus === 'error'
                  ? t('sandbox.remoteDesktopError')
                  : t('sandbox.remoteDesktopIdle')}
          </Badge>
        </span>
        <span className="remote-desktop-surface__controls">
          <label>
            <span className="sr-only">{t('sandbox.remoteDesktopResolution')}</span>
            <select
              aria-label={t('sandbox.remoteDesktopResolution')}
              value={resolution}
              onChange={(event) =>
                changeResolution(event.currentTarget.value as RemoteDesktopResolution)
              }
            >
              {RESOLUTIONS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <Button
            size="1"
            variant="soft"
            disabled={status === 'starting'}
            onClick={session ? reconnect : () => void onStart()}
          >
            <ReloadIcon />
            {session
              ? t('sandbox.remoteDesktopReconnect')
              : t('sandbox.remoteDesktopStart')}
          </Button>
          <Button
            size="1"
            variant="soft"
            disabled={!session}
            aria-label={
              isFullscreen
                ? t('sandbox.remoteDesktopExitFullscreen')
                : t('sandbox.remoteDesktopFullscreen')
            }
            onClick={() => void toggleFullscreen()}
          >
            {isFullscreen ? <ExitFullScreenIcon /> : <EnterFullScreenIcon />}
          </Button>
        </span>
      </header>

      <div
        className="remote-desktop-surface__capabilities"
        aria-label={t('sandbox.remoteDesktopFeatures')}
      >
        <Badge variant="outline">{t('sandbox.remoteDesktopClipboard')}</Badge>
        <Badge variant="outline">
          <SpeakerLoudIcon />
          {t('sandbox.remoteDesktopAudio')}
        </Badge>
        <Badge variant="outline">{t('sandbox.remoteDesktopAdaptiveResolution')}</Badge>
        <Badge variant="outline">{t('sandbox.remoteDesktopCookieAuth')}</Badge>
      </div>

      {reasonCode ? (
        <Text
          className="remote-desktop-surface__reason"
          size="1"
          color="red"
          role="alert"
        >
          {t('sandbox.remoteDesktopError')} · <code>{reasonCode}</code>
        </Text>
      ) : null}

      {session ? (
        <div className="remote-desktop-surface__frame">
          {frameStatus === 'loading' ? (
            <Text size="2" role="status">
              {t('sandbox.remoteDesktopConnecting')}
            </Text>
          ) : null}
          <iframe
            key={`${session.frame_url}:${sessionRevision}`}
            src={session.frame_url}
            title={t('sandbox.desktopFrameTitle')}
            sandbox="allow-scripts allow-same-origin allow-forms allow-pointer-lock"
            allow="autoplay; clipboard-read; clipboard-write"
            allowFullScreen
            referrerPolicy="no-referrer"
            onLoad={() => {
              retryAttemptRef.current = 0;
              setFrameStatus('ready');
            }}
            onError={() => setFrameStatus('error')}
          />
        </div>
      ) : (
        <div className="remote-desktop-surface__empty">
          <Text size="2">{t('sandbox.desktopEmptyDescription')}</Text>
          <Button
            size="2"
            disabled={status === 'starting'}
            onClick={() => void onStart()}
          >
            {status === 'starting'
              ? t('sandbox.remoteDesktopConnecting')
              : t('sandbox.remoteDesktopStart')}
          </Button>
        </div>
      )}
    </section>
  );
}
