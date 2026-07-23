const DEFAULT_UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1_000;

type UpdateClient = {
  autoDownload: boolean;
  autoInstallOnAppQuit: boolean;
  checkForUpdatesAndNotify: () => Promise<unknown>;
  on: (event: 'error', listener: () => void) => unknown;
  removeListener: (event: 'error', listener: () => void) => unknown;
};

type IntervalHandle = ReturnType<typeof setInterval>;

type AutomaticUpdateLoopOptions = {
  intervalMs?: number;
  schedule?: (callback: () => void, intervalMs: number) => IntervalHandle;
  cancel?: (handle: IntervalHandle) => void;
  report?: (message: string) => void;
};

export function startAutomaticUpdateLoop(
  updateClient: UpdateClient,
  options: AutomaticUpdateLoopOptions = {},
): () => void {
  const report =
    options.report ??
    ((message: string) => {
      process.stderr.write(`${message}\n`);
    });
  const onError = (): void => report('automatic update operation failed');
  const check = (): void => {
    void Promise.resolve()
      .then(() => updateClient.checkForUpdatesAndNotify())
      .catch(() => report('automatic update check failed'));
  };

  updateClient.autoDownload = true;
  updateClient.autoInstallOnAppQuit = true;
  updateClient.on('error', onError);
  check();

  const schedule = options.schedule ?? setInterval;
  const interval = schedule(
    check,
    options.intervalMs ?? DEFAULT_UPDATE_CHECK_INTERVAL_MS,
  );
  interval.unref?.();

  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    (options.cancel ?? clearInterval)(interval);
    updateClient.removeListener('error', onError);
  };
}
