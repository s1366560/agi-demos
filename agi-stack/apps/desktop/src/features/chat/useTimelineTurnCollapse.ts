import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  collapsedTimelineTurnStorageKey,
  readCollapsedTimelineTurnIds,
  writeCollapsedTimelineTurnIds,
  type TimelineTurnCollapseScope,
} from './timelineTurnCollapseModel';

type CollapseSnapshot = {
  storageKey: string;
  turnIds: string[];
};

export function useTimelineTurnCollapse(scope: TimelineTurnCollapseScope) {
  const stableScope = useMemo<TimelineTurnCollapseScope>(
    () => ({ ...scope }),
    [
      scope.apiBaseUrl,
      scope.conversationId,
      scope.mode,
      scope.projectId,
      scope.tenantId,
    ],
  );
  const storageKey = useMemo(
    () => collapsedTimelineTurnStorageKey(stableScope),
    [stableScope],
  );
  const [snapshot, setSnapshot] = useState<CollapseSnapshot>(() => ({
    storageKey,
    turnIds: readCollapsedTimelineTurnIds(window.localStorage, stableScope),
  }));
  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;

  useEffect(() => {
    setSnapshot({
      storageKey,
      turnIds: readCollapsedTimelineTurnIds(window.localStorage, stableScope),
    });
  }, [stableScope, storageKey]);

  const currentTurnIds = useCallback(() => {
    const current = snapshotRef.current;
    return current.storageKey === storageKey
      ? current.turnIds
      : readCollapsedTimelineTurnIds(window.localStorage, stableScope);
  }, [stableScope, storageKey]);

  const commitTurnIds = useCallback(
    (turnIds: string[]) => {
      const next = { storageKey, turnIds };
      snapshotRef.current = next;
      writeCollapsedTimelineTurnIds(window.localStorage, stableScope, turnIds);
      setSnapshot(next);
    },
    [stableScope, storageKey],
  );

  const toggleTurn = useCallback(
    (turnId: string) => {
      const current = currentTurnIds();
      commitTurnIds(
        current.includes(turnId)
          ? current.filter((candidate) => candidate !== turnId)
          : [...current, turnId],
      );
    },
    [commitTurnIds, currentTurnIds],
  );

  const expandTurn = useCallback(
    (turnId: string): boolean => {
      const current = currentTurnIds();
      if (!current.includes(turnId)) return false;
      commitTurnIds(current.filter((candidate) => candidate !== turnId));
      return true;
    },
    [commitTurnIds, currentTurnIds],
  );

  return {
    collapsedTurnIds: snapshot.storageKey === storageKey ? snapshot.turnIds : [],
    toggleTurn,
    expandTurn,
  };
}
