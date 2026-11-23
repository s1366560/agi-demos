export type WebExecutionRun = {
  status: string;
  execution_target?: 'local' | 'cloud' | null;
  local_root_label?: string | null;
};

export type WebComposerPlacement = {
  offersLocal: false;
  readOnly: boolean;
  target: 'local' | 'cloud';
  localRootLabel: string | null;
};

/** Web never offers this computer. A non-cancelled local run stays view-only. */
export function webComposerPlacement(
  run: WebExecutionRun | null | undefined
): WebComposerPlacement {
  if (run && run.status !== 'cancelled' && run.execution_target === 'local') {
    return {
      offersLocal: false,
      readOnly: true,
      target: 'local',
      localRootLabel: publicDirectoryLabel(run.local_root_label),
    };
  }
  return {
    offersLocal: false,
    readOnly: false,
    target: 'cloud',
    localRootLabel: null,
  };
}

export function publicDirectoryLabel(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed || /[/\\:]/u.test(trimmed)) return null;
  return trimmed;
}

/** Web never creates a local run. Desktop registration is a separate protocol. */
export function webCanCreateLocalRun(): false {
  return false;
}

export function inheritableWebRun<T extends WebExecutionRun & { updated_at?: string | null }>(
  runs: readonly T[],
): T | null {
  let selected: { run: T; rank: number } | null = null;
  runs.forEach((run, index) => {
    if (run.status === 'cancelled') return;
    const parsed = Date.parse(run.updated_at || '');
    const rank = Number.isFinite(parsed) ? parsed : index;
    if (!selected || rank >= selected.rank) selected = { run, rank };
  });
  return selected?.run ?? null;
}

export function webCloudWire(): {
  execution_target: 'cloud';
  execution_machine_id: null;
  execution_environment_id: null;
  local_root_label: null;
} {
  return {
    execution_target: 'cloud',
    execution_machine_id: null,
    execution_environment_id: null,
    local_root_label: null,
  };
}
