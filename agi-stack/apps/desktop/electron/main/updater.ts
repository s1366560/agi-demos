import { app } from 'electron';
import electronUpdater, { type AppUpdater } from 'electron-updater';

import { startAutomaticUpdateLoop } from './automaticUpdateLoop';
import { releaseUpdateFeedIsEnabled } from './updatePolicy';

function updater(): AppUpdater {
  const { autoUpdater } = electronUpdater;
  return autoUpdater;
}

/**
 * Starts signed-package update checks. Development builds never contact the
 * release provider and electron-builder supplies the packaged feed metadata.
 */
export function startAutomaticUpdates(): () => void {
  if (!releaseUpdateFeedIsEnabled(app.isPackaged, process.resourcesPath)) {
    return () => undefined;
  }
  return startAutomaticUpdateLoop(updater());
}
