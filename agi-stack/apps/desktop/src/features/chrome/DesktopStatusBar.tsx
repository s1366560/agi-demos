import { useI18n } from '../../i18n';
import type { ConnectionState } from '../../types';
import './DesktopStatusBar.css';

type DesktopStatusBarProps = {
  connection: ConnectionState;
  liveConnected: boolean;
  liveError: string | null;
  tenantName: string;
  projectName: string;
  onOpenConnectionSettings?: () => void;
};

/**
 * Bottom status bar rendered in both the native and browser shells. Purely
 * presentational: every segment reflects state the App shell already owns.
 */
export function DesktopStatusBar({
  connection,
  liveConnected,
  liveError,
  onOpenConnectionSettings,
}: DesktopStatusBarProps) {
  const { t } = useI18n();

  // Healthy connections remain available in Settings without occupying a row.
  const runtimeUnavailable = connection !== 'ready';
  if (!runtimeUnavailable && liveConnected && !liveError) return null;

  return (
    <footer className="desktop-status-bar" role="status" aria-live="polite">
      <span className="desktop-status-bar-segment" data-tone={connection}>
        {runtimeUnavailable
          ? `${t('statusbar.runtime')}: ${t(`runtime.status.${connection}`)}`
          : `${t('statusbar.live')}: ${t('statusbar.disconnected')}`}
      </span>
      {liveError ? <span className="desktop-status-bar-error">{liveError}</span> : null}
      {onOpenConnectionSettings ? (
        <button type="button" onClick={onOpenConnectionSettings}>
          {t('settings.connectionRecovery')}
        </button>
      ) : null}
    </footer>
  );
}
