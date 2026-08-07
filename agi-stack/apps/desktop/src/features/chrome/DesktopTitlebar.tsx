import { PinLeftIcon, PinRightIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { WindowControls } from './WindowControls';
import './DesktopTitlebar.css';

type DesktopTitlebarProps = {
  contextTitle: string;
  sidebarCollapsed: boolean;
  rightSidebarOpen: boolean;
  rightSidebarAvailable?: boolean;
  onToggleSidebar: () => void;
  onToggleRightSidebar: () => void;
};

/**
 * Frameless-window titlebar for the native desktop shell. The whole strip is
 * a drag region; every interactive element opts out via `no-drag`. macOS
 * keeps the native traffic lights, so an inset pad reserves their space,
 * while Windows and Linux get the self-drawn WindowControls instead.
 */
export function DesktopTitlebar({
  contextTitle,
  sidebarCollapsed,
  rightSidebarOpen,
  rightSidebarAvailable = true,
  onToggleSidebar,
  onToggleRightSidebar,
}: DesktopTitlebarProps) {
  const { t } = useI18n();
  const platform = window.__MEMSTACK_DESKTOP__?.platform ?? 'darwin';

  return (
    <header className="desktop-titlebar">
      {platform === 'darwin' ? (
        <div className="desktop-titlebar-traffic-pad" aria-hidden="true" />
      ) : null}
      <button
        type="button"
        className="desktop-titlebar-button"
        aria-label={t('titlebar.toggleSidebar')}
        aria-pressed={!sidebarCollapsed}
        title={t('titlebar.toggleSidebar')}
        onClick={onToggleSidebar}
      >
        <PinLeftIcon />
      </button>
      <span className="desktop-titlebar-title" title={contextTitle}>
        {contextTitle}
      </span>
      <div className="desktop-titlebar-actions">
        <button
          type="button"
          className="desktop-titlebar-button"
          aria-label={t('titlebar.toggleRightPanel')}
          aria-pressed={rightSidebarOpen}
          title={t('titlebar.toggleRightPanel')}
          disabled={!rightSidebarAvailable}
          onClick={onToggleRightSidebar}
        >
          <PinRightIcon />
        </button>
        {platform !== 'darwin' ? <WindowControls /> : null}
      </div>
    </header>
  );
}
