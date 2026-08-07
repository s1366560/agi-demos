import { useEffect, useState } from 'react';

import { CopyIcon, Cross2Icon, MinusIcon, SquareIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';

/**
 * Self-drawn minimize/maximize/close controls for frameless Windows and
 * Linux shells. All actions go through the preload windowControls bridge.
 * The maximized state is authoritative in the main process: the toggle
 * action resolves there, and the icon state is seeded/confirmed from
 * `isMaximized()` so external maximizes (titlebar double-click, Aero Snap,
 * display changes) cannot desync the control.
 */
export function WindowControls() {
  const { t } = useI18n();
  const [maximized, setMaximized] = useState(false);
  const bridge = window.__MEMSTACK_DESKTOP__?.windowControls;

  useEffect(() => {
    if (!bridge) return;
    let cancelled = false;
    void bridge.isMaximized().then((value) => {
      if (!cancelled) setMaximized(value);
    });
    return () => {
      cancelled = true;
    };
  }, [bridge]);

  if (!bridge) return null;

  const toggleMaximize = () => {
    // Optimistic icon flip; the authoritative maximize/unmaximize decision is
    // made in the main process from the real window state.
    setMaximized(!maximized);
    void bridge.toggleMaximize().then(() => bridge.isMaximized().then(setMaximized));
  };

  return (
    <div className="desktop-titlebar-window-buttons">
      <button
        type="button"
        className="desktop-titlebar-button"
        aria-label={t('titlebar.minimize')}
        title={t('titlebar.minimize')}
        onClick={() => void bridge.minimize()}
      >
        <MinusIcon />
      </button>
      <button
        type="button"
        className="desktop-titlebar-button"
        aria-label={maximized ? t('titlebar.restore') : t('titlebar.maximize')}
        title={maximized ? t('titlebar.restore') : t('titlebar.maximize')}
        onClick={toggleMaximize}
      >
        {maximized ? <CopyIcon /> : <SquareIcon />}
      </button>
      <button
        type="button"
        className="desktop-titlebar-button desktop-titlebar-close-button"
        aria-label={t('titlebar.close')}
        title={t('titlebar.close')}
        onClick={() => void bridge.close()}
      >
        <Cross2Icon />
      </button>
    </div>
  );
}
