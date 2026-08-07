import { useState } from 'react';

import { CopyIcon, Cross2Icon, MinusIcon, SquareIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';

/**
 * Self-drawn minimize/maximize/close controls for frameless Windows and
 * Linux shells. All actions go through the preload windowControls bridge;
 * the maximized state is tracked locally per click because the shell only
 * exposes actions, not window-state queries.
 */
export function WindowControls() {
  const { t } = useI18n();
  const [maximized, setMaximized] = useState(false);
  const bridge = window.__MEMSTACK_DESKTOP__?.windowControls;
  if (!bridge) return null;

  const toggleMaximize = () => {
    if (maximized) {
      void bridge.unmaximize();
    } else {
      void bridge.maximize();
    }
    setMaximized(!maximized);
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
