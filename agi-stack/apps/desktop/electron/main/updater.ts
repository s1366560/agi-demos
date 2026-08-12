import { app } from 'electron';
import electronUpdater, { type AppUpdater } from 'electron-updater';

import {
  startAutomaticUpdateLoop,
  type AutomaticUpdateController,
} from './automaticUpdateLoop';
import { createUpdateLifecycleState } from './updateLifecycle';
import type { UpdateRecoveryJournal } from './updateRecoveryJournal';
import { resolveUpdateRecoveryInstallation } from './updateRecoveryInstallation';
import {
  clearPreparedUpdateRecovery,
  launchUpdateRecoveryHelper,
  prepareUpdateRecoverySnapshot,
} from './updateRecoveryProcess';
import { releaseUpdateFeedIsEnabled } from './updatePolicy';

function updater(): AppUpdater {
  const { autoUpdater } = electronUpdater;
  return autoUpdater;
}

/**
 * Starts signed-package update checks. Development builds never contact the
 * release provider and electron-builder supplies the packaged feed metadata.
 */
function disabledController(reasonCode: string): AutomaticUpdateController {
  const state = createUpdateLifecycleState({
    phase: 'disabled',
    currentVersion: app.getVersion(),
    candidateVersion: null,
    recoveryVersion: null,
    progress: null,
    reasonCode,
    retryable: false,
    allowedActions: [],
  });
  return Object.freeze({
    getState: () => state,
    check: async () => undefined,
    restartToApply: () => {
      throw new Error('update is not ready to install');
    },
    confirmHealthy: () => undefined,
    subscribe: (listener) => {
      listener(state);
      return () => undefined;
    },
    stop: () => undefined,
  });
}

export function startAutomaticUpdates(options: {
  journal: UpdateRecoveryJournal;
  recoveryHelperBinaryPath: string;
  recoveryRoot: string;
}): AutomaticUpdateController {
  if (!releaseUpdateFeedIsEnabled(app.isPackaged, process.resourcesPath)) {
    return disabledController('production_update_feed_disabled');
  }
  const installation = resolveUpdateRecoveryInstallation({
    platform: process.platform,
    executablePath: process.execPath,
    appImagePath: process.env.APPIMAGE,
  });
  if (installation.management === 'externally_managed') {
    return disabledController(installation.reasonCode);
  }
  return startAutomaticUpdateLoop(updater(), {
    currentVersion: app.getVersion(),
    journal: options.journal,
    prepareRecoverySnapshot: ({ currentVersion }) =>
      prepareUpdateRecoverySnapshot({
        helperSourcePath: options.recoveryHelperBinaryPath,
        journalPath: options.journal.path,
        ownedRoot: options.recoveryRoot,
        currentVersion,
        installation,
      }),
    clearRecoverySnapshot: () => clearPreparedUpdateRecovery(options.recoveryRoot),
    launchRecoveryHelper: (record) => {
      launchUpdateRecoveryHelper({
        ownedRoot: options.recoveryRoot,
        journalPath: options.journal.path,
        record,
      });
    },
  });
}
