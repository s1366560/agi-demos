import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { InstanceTemplatesController } from './instanceTemplatesController';
import type {
  InstanceTemplateCreateInput,
  InstanceTemplatesQuery,
  InstanceTemplatesScope,
} from './instanceTemplatesTypes';

export function useInstanceTemplatesController(
  controller: InstanceTemplatesController,
  scope: InstanceTemplatesScope,
) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.stop();
  }, [controller, scope.authority, scope.tenantId]);
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);
  const setQuery = useCallback(
    (query: InstanceTemplatesQuery) => {
      void controller.setQuery(query);
    },
    [controller],
  );
  const setFilters = useCallback(
    (query: InstanceTemplatesQuery) => controller.setFilters(query),
    [controller],
  );
  const inspect = useCallback(
    (templateId: string) => controller.inspect(templateId),
    [controller],
  );
  const closeDetail = useCallback(
    () => controller.closeDetail(),
    [controller],
  );
  const create = useCallback(
    (input: InstanceTemplateCreateInput) => controller.create(input),
    [controller],
  );
  const remove = useCallback(
    (templateId: string) => controller.delete(templateId),
    [controller],
  );
  const publish = useCallback(
    (templateId: string) => controller.publish(templateId),
    [controller],
  );
  const clone = useCallback(
    (templateId: string, newName: string) =>
      controller.clone(templateId, newName),
    [controller],
  );
  return {
    model,
    retry,
    setQuery,
    setFilters,
    inspect,
    closeDetail,
    create,
    remove,
    publish,
    clone,
  };
}
