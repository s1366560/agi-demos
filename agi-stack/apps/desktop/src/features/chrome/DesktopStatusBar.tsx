import { useI18n } from '../../i18n';
import type { ConnectionState } from '../../types';
import './DesktopStatusBar.css';

type DesktopStatusBarProps = {
  connection: ConnectionState;
  liveConnected: boolean;
  liveError: string | null;
  tenantName: string;
  projectName: string;
};

/**
 * Bottom status bar rendered in both the native and browser shells. Purely
 * presentational: every segment reflects state the App shell already owns.
 */
export function DesktopStatusBar({
  connection,
  liveConnected,
  liveError,
  tenantName,
  projectName,
}: DesktopStatusBarProps) {
  const { t } = useI18n();

  return (
    <footer className="desktop-status-bar">
      <span className="desktop-status-bar-segment" data-tone={connection}>
        {t('statusbar.runtime')}: {t(`runtime.status.${connection}`)}
      </span>
      <span
        className="desktop-status-bar-segment"
        data-tone={liveError ? 'error' : liveConnected ? 'ready' : 'idle'}
        title={liveError ?? undefined}
      >
        {t('statusbar.live')}:{' '}
        {liveConnected ? t('statusbar.connected') : t('statusbar.disconnected')}
      </span>
      <span className="desktop-status-bar-spacer" />
      <span className="desktop-status-bar-segment desktop-status-bar-context">
        {tenantName} · {projectName}
      </span>
    </footer>
  );
}
