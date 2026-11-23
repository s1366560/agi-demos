/**
 * Desktop execution placement for the composer.
 *
 * The absolute local directory stays on this computer. Cloud payloads only
 * receive the basename label and the redacted run record.
 */

export const EXECUTION_PLACEMENT_STORAGE_KEY = 'agistack.desktop.execution-placement.v1';

/** Local runs register on the cloud and execute on this computer. */
export const LOCAL_EXECUTION_PROTOCOL_AVAILABLE = true;

export type ExecutionPlacementTarget = 'local' | 'cloud';

export type ExecutionPlacementPreference = {
  target: ExecutionPlacementTarget;
  /** Absolute path stored only on this computer. Null uses the sidecar default root. */
  localRoot: string | null;
};

export type ExecutionPlacementRun = {
  status: string;
  execution_target?: 'local' | 'cloud' | null;
  execution_machine_id?: string | null;
  execution_environment_id?: string | null;
  local_root_label?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
};

export type PublicExecutionWire = {
  execution_target: 'cloud';
  execution_machine_id: null;
  execution_environment_id: null;
  local_root_label: null;
};

export type LocalExecutionWire = {
  execution_target: 'local';
  execution_machine_id: string;
  execution_environment_id: null;
  local_root_label: string;
};

export type MessagePermissionMode = 'ask' | 'automatic' | 'full_access';

export type ExecutionSendBlockCode =
  | 'LOCAL_EXECUTION_UNAVAILABLE'
  | 'LOCAL_ROOT_UNAVAILABLE'
  | 'LOCAL_ROOT_CONFIG_FAILED'
  | 'EXECUTION_PERMISSION_DENIED'
  | 'EXECUTION_TARGET_SWITCH_FAILED'
  | 'WEB_LOCAL_RUN_READONLY';

export type ExecutionSendDecision =
  | {
      ok: true;
      transport: 'cloud';
      wire: PublicExecutionWire;
      permissionMode: null;
    }
  | {
      ok: true;
      transport: 'local';
      wire: LocalExecutionWire;
      /** Absolute directory. It stays on this computer and is not part of `wire`. */
      localRoot: string;
      permissionMode: null;
      sync: 'pending';
    }
  | {
      ok: false;
      code: ExecutionSendBlockCode;
    };

type PlacementStorage = Pick<Storage, 'getItem' | 'setItem'>;

type StoredScope = {
  target: ExecutionPlacementTarget;
  localRoot: string | null;
};

type StoredDocument = {
  version: 1;
  machineId: string;
  scopes: Record<string, StoredScope>;
};

const ACTIVE_RUN_STATUSES = new Set(['queued', 'running']);

export function executionPlacementScope(userId: string, projectId: string): string | null {
  const user = userId.trim();
  const project = projectId.trim();
  if (!user || !project) return null;
  return `${user}\u0000${project}`;
}

export function defaultExecutionPlacementPreference(): ExecutionPlacementPreference {
  return { target: 'local', localRoot: null };
}

export function localRootBasename(path: string | null | undefined): string | null {
  if (typeof path !== 'string') return null;
  const trimmed = path.trim();
  if (!trimmed) return null;
  const normalized = trimmed.replaceAll('\\', '/').replace(/\/+$/u, '');
  const slash = normalized.lastIndexOf('/');
  const base = slash >= 0 ? normalized.slice(slash + 1) : normalized;
  if (!base || base === '.' || base === '..') return null;
  if (/[/\\:]/u.test(base)) return null;
  return base;
}

export function wireContainsAbsolutePath(
  wire: object,
  absolutePaths: readonly string[],
): boolean {
  const serialized = JSON.stringify(wire);
  return absolutePaths.some((path) => {
    const candidate = path.trim();
    return candidate.length > 0 && serialized.includes(candidate);
  });
}

export function cloudExecutionWire(): PublicExecutionWire {
  return {
    execution_target: 'cloud',
    execution_machine_id: null,
    execution_environment_id: null,
    local_root_label: null,
  };
}

/**
 * Chat preset `full` is the broad permission. It must stay `full_access`.
 * `default` is omitted so a turn does not narrow a broader canonical mode.
 */
export function messagePermissionMode(
  preset: 'default' | 'relaxed' | 'full' | null | undefined,
  pending = false,
): MessagePermissionMode | null {
  if (pending || preset == null || preset === 'default') return null;
  if (preset === 'full') return 'full_access';
  return 'automatic';
}

export function readExecutionMachineId(
  storage: PlacementStorage | null,
): string | null {
  const document = readDocument(storage);
  return document?.machineId ?? null;
}

export function readExecutionPlacementPreference(
  scope: string | null,
  storage: PlacementStorage | null,
): ExecutionPlacementPreference {
  if (!scope) return defaultExecutionPlacementPreference();
  const stored = readDocument(storage)?.scopes[scope];
  if (!stored) return defaultExecutionPlacementPreference();
  return {
    target: stored.target === 'cloud' ? 'cloud' : 'local',
    localRoot: absoluteLocalRoot(stored.localRoot),
  };
}

export function writeExecutionPlacementPreference(
  scope: string | null,
  preference: ExecutionPlacementPreference,
  storage: PlacementStorage | null,
  machineId: string,
): void {
  if (!scope || !storage) return;
  const current = readDocument(storage) ?? emptyDocument(machineId);
  const next: StoredDocument = {
    version: 1,
    machineId: current.machineId || machineId,
    scopes: {
      ...current.scopes,
      [scope]: {
        target: preference.target === 'cloud' ? 'cloud' : 'local',
        localRoot: absoluteLocalRoot(preference.localRoot),
      },
    },
  };
  try {
    storage.setItem(EXECUTION_PLACEMENT_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // The in-memory preference remains authoritative when storage is unavailable.
  }
}

export function inheritableExecutionRun<T extends ExecutionPlacementRun>(
  runs: readonly T[],
): T | null {
  let selected: { run: T; rank: number } | null = null;
  for (let index = 0; index < runs.length; index += 1) {
    const run = runs[index];
    if (!run || run.status === 'cancelled') continue;
    const rank = recencyRank(run, index);
    if (!selected || rank > selected.rank) selected = { run, rank };
  }
  return selected?.run ?? null;
}

export function executionRunIsActive(status: string | null | undefined): boolean {
  return ACTIVE_RUN_STATUSES.has(status?.trim().toLowerCase() ?? '');
}

export function localPathMatchesRun(input: {
  configuredRoot: string | null;
  label: string | null;
  runMachineId: string | null;
  localMachineId: string | null;
}): boolean {
  const label = input.label?.trim() || null;
  const configured = localRootBasename(input.configuredRoot);
  if (!label || !configured || configured !== label) return false;
  if (
    input.runMachineId &&
    input.localMachineId &&
    input.runMachineId !== input.localMachineId
  ) {
    return false;
  }
  return true;
}

export function decideExecutionSwitch(active: boolean): ExecutionSendDecision | { ok: true } {
  if (active) return { ok: false, code: 'EXECUTION_TARGET_SWITCH_FAILED' };
  return { ok: true };
}

export function decideDirectoryConfig(input: {
  previous: ExecutionPlacementPreference;
  selectedPath: string | null;
  failed: boolean;
  permissionDenied?: boolean;
}): { ok: true; preference: ExecutionPlacementPreference } | { ok: false; code: ExecutionSendBlockCode } {
  if (input.permissionDenied) return { ok: false, code: 'EXECUTION_PERMISSION_DENIED' };
  const root = absoluteLocalRoot(input.selectedPath);
  if (input.failed || !root) return { ok: false, code: 'LOCAL_ROOT_CONFIG_FAILED' };
  return {
    ok: true,
    preference: { target: 'local', localRoot: root },
  };
}

export type ResolvedComposerPlacement = {
  target: ExecutionPlacementTarget;
  localRootLabel: string | null;
  pathUnavailable: boolean;
  readOnly: boolean;
  source: 'preference' | 'run';
};

export function resolveComposerPlacement(input: {
  surface: 'desktop' | 'web';
  preference: ExecutionPlacementPreference;
  configuredRoot: string | null;
  runs: readonly ExecutionPlacementRun[];
  active: boolean;
  localMachineId: string | null;
  sessionOverride: ExecutionPlacementTarget | null;
}): ResolvedComposerPlacement {
  const inherited = input.sessionOverride ? null : inheritableExecutionRun(input.runs);
  if (input.surface === 'web') {
    const target = inherited?.execution_target === 'local' ? 'local' : 'cloud';
    return {
      target,
      localRootLabel:
        target === 'local' ? localRootBasename(inherited?.local_root_label) : null,
      pathUnavailable: false,
      readOnly: true,
      source: inherited ? 'run' : 'preference',
    };
  }
  if (inherited) {
    const target = inherited.execution_target === 'local' ? 'local' : 'cloud';
    const label =
      target === 'local' ? localRootBasename(inherited.local_root_label) : null;
    const pathUnavailable =
      target === 'local' &&
      !localPathMatchesRun({
        configuredRoot: input.preference.localRoot ?? input.configuredRoot,
        label,
        runMachineId: inherited.execution_machine_id ?? null,
        localMachineId: input.localMachineId,
      });
    return {
      target,
      localRootLabel: label,
      pathUnavailable,
      readOnly: input.active,
      source: 'run',
    };
  }
  const target = input.sessionOverride ?? input.preference.target;
  const root = input.preference.localRoot ?? input.configuredRoot;
  return {
    target,
    localRootLabel: target === 'local' ? localRootBasename(root) : null,
    pathUnavailable: target === 'local' && !localRootBasename(root),
    readOnly: input.active,
    source: 'preference',
  };
}

export function decideExecutionSend(input: {
  surface: 'desktop' | 'web';
  placement: ResolvedComposerPlacement;
  permissionDenied?: boolean;
  machineId?: string | null;
  localRoot?: string | null;
}): ExecutionSendDecision {
  if (input.permissionDenied) return { ok: false, code: 'EXECUTION_PERMISSION_DENIED' };
  if (input.surface === 'web' && input.placement.target === 'local') {
    return { ok: false, code: 'WEB_LOCAL_RUN_READONLY' };
  }
  if (input.placement.target === 'local') {
    if (input.placement.pathUnavailable || !input.placement.localRootLabel) {
      return { ok: false, code: 'LOCAL_ROOT_UNAVAILABLE' };
    }
    const machineId = input.machineId?.trim() ?? '';
    const localRoot = absoluteLocalRoot(input.localRoot);
    if (!LOCAL_EXECUTION_PROTOCOL_AVAILABLE || !machineId || !localRoot) {
      return { ok: false, code: 'LOCAL_EXECUTION_UNAVAILABLE' };
    }
    if (localRootBasename(localRoot) !== input.placement.localRootLabel) {
      return { ok: false, code: 'LOCAL_ROOT_UNAVAILABLE' };
    }
    return {
      ok: true,
      transport: 'local',
      wire: {
        execution_target: 'local',
        execution_machine_id: machineId,
        execution_environment_id: null,
        local_root_label: input.placement.localRootLabel,
      },
      localRoot,
      permissionMode: null,
      sync: 'pending',
    };
  }
  return {
    ok: true,
    transport: 'cloud',
    wire: cloudExecutionWire(),
    // The approval preset stays on the conversation config. Requesting it as
    // this turn's permission_mode is rejected when the workspace ceiling is ask.
    permissionMode: null,
  };
}

export function webOffersLocalTarget(): false {
  return false;
}

const EXECUTION_SEND_BLOCK_KEY: Record<ExecutionSendBlockCode, string> = {
  LOCAL_EXECUTION_UNAVAILABLE: 'executionPlacement.localExecutionUnavailable',
  LOCAL_ROOT_UNAVAILABLE: 'executionPlacement.directoryUnavailable',
  LOCAL_ROOT_CONFIG_FAILED: 'executionPlacement.pathConfigFailed',
  EXECUTION_PERMISSION_DENIED: 'executionPlacement.permissionDenied',
  EXECUTION_TARGET_SWITCH_FAILED: 'executionPlacement.switchBlocked',
  WEB_LOCAL_RUN_READONLY: 'executionPlacement.webLocalReadonly',
};

export function executionPlacementMessageKey(code: ExecutionSendBlockCode): string {
  return EXECUTION_SEND_BLOCK_KEY[code];
}

export function placementNoticeCode(input: {
  placement: ResolvedComposerPlacement;
  noticeCode: ExecutionSendBlockCode | null;
}): ExecutionSendBlockCode | null {
  if (
    input.noticeCode === 'EXECUTION_TARGET_SWITCH_FAILED' ||
    input.noticeCode === 'LOCAL_ROOT_CONFIG_FAILED' ||
    input.noticeCode === 'EXECUTION_PERMISSION_DENIED'
  ) {
    return input.noticeCode;
  }
  if (input.placement.pathUnavailable) return 'LOCAL_ROOT_UNAVAILABLE';
  return null;
}

function recencyRank(run: ExecutionPlacementRun, index: number): number {
  const raw = Date.parse(run.updated_at || run.created_at || '');
  if (Number.isFinite(raw)) return raw;
  return Number.MAX_SAFE_INTEGER - index;
}

function absoluteLocalRoot(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const posix = trimmed.startsWith('/');
  const windows = /^[A-Za-z]:[\\/]/u.test(trimmed);
  if (!posix && !windows) return null;
  if (!localRootBasename(trimmed)) return null;
  return trimmed;
}

function emptyDocument(machineId: string): StoredDocument {
  return { version: 1, machineId, scopes: {} };
}

function readDocument(storage: PlacementStorage | null): StoredDocument | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(EXECUTION_PLACEMENT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredDocument>;
    if (parsed.version !== 1 || typeof parsed.machineId !== 'string' || !parsed.machineId.trim()) {
      return null;
    }
    const scopes: Record<string, StoredScope> = {};
    if (parsed.scopes && typeof parsed.scopes === 'object') {
      for (const [key, value] of Object.entries(parsed.scopes)) {
        if (!value || typeof value !== 'object') continue;
        const target = value.target === 'cloud' ? 'cloud' : value.target === 'local' ? 'local' : null;
        if (!target) continue;
        scopes[key] = {
          target,
          localRoot: absoluteLocalRoot(
            typeof value.localRoot === 'string' ? value.localRoot : null,
          ),
        };
      }
    }
    return { version: 1, machineId: parsed.machineId.trim(), scopes };
  } catch {
    return null;
  }
}
