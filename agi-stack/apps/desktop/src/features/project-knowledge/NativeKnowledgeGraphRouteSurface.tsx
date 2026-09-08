import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';
import type { DesktopRouteSurfaceProps } from '../navigation/desktopRouteModule';
import {
  useNativeMemoriesRouteBinding,
  type NativeMemoriesRouteBinding,
} from './NativeMemoriesRouteContext';
import { NativeMemoriesUnavailable } from './NativeMemoriesPage';
import { createNativeKnowledgeGraphController } from './nativeKnowledgeGraphController';
import { NativeKnowledgeGraphPage } from './NativeKnowledgeGraphPage';

export function NativeKnowledgeGraphRouteSurface({ context }: DesktopRouteSurfaceProps) {
  const binding = useNativeMemoriesRouteBinding();
  if (
    !binding ||
    !binding.authority.available ||
    binding.authority.scope.authority !== 'local' ||
    context.tenantId !== binding.authority.scope.tenantId ||
    context.projectId !== binding.authority.scope.projectId
  )
    return <NativeMemoriesUnavailable />;
  return <BoundGraphRoute key={JSON.stringify(binding.authority)} binding={binding} />;
}
function BoundGraphRoute({ binding }: Readonly<{ binding: NativeMemoriesRouteBinding }>) {
  const controller = useMemo(() => createNativeKnowledgeGraphController(binding), [binding]);
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useLayoutEffect(() => {
    controller.activate();
    void controller.refresh();
    return controller.stop;
  }, [controller]);
  return <NativeKnowledgeGraphPage model={model} controller={controller} />;
}
