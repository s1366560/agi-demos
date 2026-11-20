import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { DesktopRun } from '../../types';
import {
  EXECUTION_PLACEMENT_STORAGE_KEY,
  decideDirectoryConfig,
  decideExecutionSend,
  decideExecutionSwitch,
  defaultExecutionPlacementPreference,
  executionPlacementScope,
  executionRunIsActive,
  readExecutionMachineId,
  readExecutionPlacementPreference,
  resolveComposerPlacement,
  writeExecutionPlacementPreference,
  type ExecutionPlacementPreference,
  type ExecutionPlacementTarget,
  type ExecutionSendBlockCode,
  type ExecutionSendDecision,
  type ResolvedComposerPlacement,
} from './executionPlacementModel';

type PlacementStorage = Pick<Storage, 'getItem' | 'setItem'>;

type RuntimeInvoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;

type LocalRuntimeRootStatus = {
  workspace_root?: string;
};

export type ExecutionPlacementController = {
  placement: ResolvedComposerPlacement;
  newTaskPlacement: ResolvedComposerPlacement;
  noticeCode: ExecutionSendBlockCode | null;
  noticeDetail: string | null;
  selectTarget: (target: ExecutionPlacementTarget, scope?: 'session' | 'new_task') => void;
  pickDirectory: (scope?: 'session' | 'new_task') => Promise<void>;
  resolveSend: (kind?: 'session' | 'new_task') => ExecutionSendDecision;
};

function browserStorage(): PlacementStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

function runtimeInvoke(): RuntimeInvoke | null {
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  return typeof invoke === 'function' ? invoke : null;
}

function machineIdFor(storage: PlacementStorage | null): string {
  const existing = readExecutionMachineId(storage);
  if (existing) return existing;
  const created = globalThis.crypto?.randomUUID?.() ?? `machine-${Date.now()}`;
  writeExecutionPlacementPreference(null, defaultExecutionPlacementPreference(), storage, created);
  const document = readExecutionMachineId(storage);
  if (document) return document;
  if (storage) {
    try {
      storage.setItem(
        EXECUTION_PLACEMENT_STORAGE_KEY,
        JSON.stringify({ version: 1, machineId: created, scopes: {} }),
      );
    } catch {
      // The session keeps the generated id when storage rejects the write.
    }
  }
  return created;
}

export function useExecutionPlacement(input: {
  userId: string;
  projectId: string;
  conversationId: string | null;
  runs: readonly DesktopRun[];
  active: boolean;
  nativeDesktop: boolean;
}): ExecutionPlacementController {
  const storage = browserStorage();
  const scope = executionPlacementScope(input.userId, input.projectId);
  const [machineId] = useState(() => machineIdFor(browserStorage()));
  const [preference, setPreference] = useState<ExecutionPlacementPreference>(() =>
    readExecutionPlacementPreference(scope, storage),
  );
  const [configuredRoot, setConfiguredRoot] = useState<string | null>(null);
  const [sessionOverride, setSessionOverride] = useState<{
    conversationId: string;
    target: ExecutionPlacementTarget;
  } | null>(null);
  const [noticeCode, setNoticeCode] = useState<ExecutionSendBlockCode | null>(null);
  const [noticeDetail, setNoticeDetail] = useState<string | null>(null);
  const preferenceRef = useRef(preference);
  preferenceRef.current = preference;

  useEffect(() => {
    setPreference(readExecutionPlacementPreference(scope, storage));
    setSessionOverride(null);
    setNoticeCode(null);
    setNoticeDetail(null);
  }, [scope, storage]);

  useEffect(() => {
    setSessionOverride(null);
  }, [input.conversationId]);

  useEffect(() => {
    if (!input.nativeDesktop) return;
    const invoke = runtimeInvoke();
    if (!invoke) return;
    let cancelled = false;
    invoke<LocalRuntimeRootStatus>('local_runtime_status')
      .then((status) => {
        if (cancelled) return;
        const root = status.workspace_root?.trim() || null;
        setConfiguredRoot(root);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setNoticeCode('LOCAL_ROOT_CONFIG_FAILED');
        setNoticeDetail(caught instanceof Error ? caught.message : String(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [input.nativeDesktop]);

  const active =
    input.active || input.runs.some((run) => executionRunIsActive(run.status));
  const placement = useMemo(
    () =>
      resolveComposerPlacement({
        surface: 'desktop',
        preference,
        configuredRoot,
        runs: input.runs,
        active,
        localMachineId: machineId,
        sessionOverride:
          sessionOverride && sessionOverride.conversationId === input.conversationId
            ? sessionOverride.target
            : null,
      }),
    [
      active,
      configuredRoot,
      input.conversationId,
      input.runs,
      machineId,
      preference,
      sessionOverride,
    ],
  );
  const newTaskPlacement = useMemo(
    () =>
      resolveComposerPlacement({
        surface: 'desktop',
        preference,
        configuredRoot,
        runs: [],
        active: false,
        localMachineId: machineId,
        sessionOverride: null,
      }),
    [configuredRoot, machineId, preference],
  );

  const persist = useCallback(
    (next: ExecutionPlacementPreference) => {
      setPreference(next);
      writeExecutionPlacementPreference(scope, next, storage, machineId);
    },
    [machineId, scope, storage],
  );

  const selectTarget = useCallback(
    (target: ExecutionPlacementTarget, scopeKind: 'session' | 'new_task' = 'session') => {
      const decision = decideExecutionSwitch(scopeKind === 'session' && placement.readOnly);
      if (!decision.ok) {
        setNoticeCode(decision.code);
        return;
      }
      setNoticeCode(target === 'local' ? 'LOCAL_EXECUTION_UNAVAILABLE' : null);
      setNoticeDetail(null);
      persist({ ...preferenceRef.current, target });
      if (scopeKind === 'session' && input.conversationId) {
        setSessionOverride({ conversationId: input.conversationId, target });
      }
    },
    [input.conversationId, persist, placement.readOnly],
  );

  const pickDirectory = useCallback(async (scopeKind: 'session' | 'new_task' = 'session') => {
    if (scopeKind === 'session' && placement.readOnly) {
      setNoticeCode('EXECUTION_TARGET_SWITCH_FAILED');
      return;
    }
    const invoke = runtimeInvoke();
    if (!invoke) {
      setNoticeCode('LOCAL_ROOT_CONFIG_FAILED');
      setNoticeDetail(null);
      return;
    }
    try {
      const picked = await invoke<{ status: 'cancelled' | 'selected'; path?: string }>(
        'choose_workspace_directory',
      );
      if (picked.status !== 'selected' || !picked.path) return;
      const configured = await invoke<LocalRuntimeRootStatus>('local_runtime_configure', {
        config: { workspace_root: picked.path },
      });
      const applied = decideDirectoryConfig({
        previous: preferenceRef.current,
        selectedPath: configured.workspace_root || picked.path,
        failed: false,
      });
      if (!applied.ok) {
        setNoticeCode(applied.code);
        return;
      }
      setConfiguredRoot(applied.preference.localRoot);
      persist(applied.preference);
      setNoticeCode('LOCAL_EXECUTION_UNAVAILABLE');
      setNoticeDetail(null);
    } catch (caught) {
      const failed = decideDirectoryConfig({
        previous: preferenceRef.current,
        selectedPath: null,
        failed: true,
      });
      setNoticeCode(failed.ok ? 'LOCAL_ROOT_CONFIG_FAILED' : failed.code);
      setNoticeDetail(caught instanceof Error ? caught.message : String(caught));
    }
  }, [persist, placement.readOnly]);

  const resolveSend = useCallback(
    (kind: 'session' | 'new_task' = 'session'): ExecutionSendDecision => {
      const decision = decideExecutionSend({
        surface: 'desktop',
        placement: kind === 'new_task' ? newTaskPlacement : placement,
      });
      if (!decision.ok) setNoticeCode(decision.code);
      return decision;
    },
    [newTaskPlacement, placement],
  );

  return {
    placement,
    newTaskPlacement,
    noticeCode,
    noticeDetail,
    selectTarget,
    pickDirectory,
    resolveSend,
  };
}
