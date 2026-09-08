import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';

import type { DesktopRouteSurfaceProps } from '../navigation/desktopRouteModule';
import {
  useNativeMemoriesRouteBinding,
  type NativeMemoriesRouteBinding,
} from './NativeMemoriesRouteContext';
import { NativeMemoriesUnavailable } from './NativeMemoriesPage';
import { createNativeKnowledgeCommunityController } from './nativeKnowledgeCommunityController';
import { NativeKnowledgeCommunitiesPage } from './NativeKnowledgeCommunitiesPage';

export function NativeKnowledgeCommunitiesRouteSurface({ context }: DesktopRouteSurfaceProps) {
  const binding = useNativeMemoriesRouteBinding();
  if (
    !binding ||
    !binding.authority.available ||
    binding.authority.scope.authority !== 'local' ||
    context.tenantId !== binding.authority.scope.tenantId ||
    context.projectId !== binding.authority.scope.projectId
  )
    return <NativeMemoriesUnavailable />;
  return <BoundCommunityRoute key={JSON.stringify(binding.authority)} binding={binding} />;
}

function BoundCommunityRoute({ binding }: Readonly<{ binding: NativeMemoriesRouteBinding }>) {
  const controller = useMemo(() => createNativeKnowledgeCommunityController(binding), [binding]);
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useLayoutEffect(() => {
    controller.activate();
    void controller.refresh().then(() => controller.loadHistory());
    return () => controller.stop();
  }, [controller]);
  return <NativeKnowledgeCommunitiesPage model={model} controller={controller} />;
}
