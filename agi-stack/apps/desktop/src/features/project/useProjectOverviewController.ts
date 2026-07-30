import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';

import type { ProjectOverviewController } from './projectOverviewController';
import type {
  ProjectOverviewPresentationModel,
  ProjectOverviewPresentationScope,
} from './projectOverviewPresentationModel';

export type ProjectOverviewControllerHookState = Readonly<{
  model: ProjectOverviewPresentationModel;
  retry: () => void;
}>;

export function useProjectOverviewController(
  controller: ProjectOverviewController,
  scope: ProjectOverviewPresentationScope,
): ProjectOverviewControllerHookState {
  const stableScope = useMemo<ProjectOverviewPresentationScope>(
    () =>
      Object.freeze({
        authority: scope.authority,
        tenantId: scope.tenantId,
        projectId: scope.projectId,
      }),
    [scope.authority, scope.projectId, scope.tenantId],
  );
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);

  useEffect(() => {
    void controller.load(stableScope);
    return controller.cancel;
  }, [controller, stableScope]);

  return useMemo(() => ({ model, retry }), [model, retry]);
}
