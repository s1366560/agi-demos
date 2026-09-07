import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';

import type { DesktopRouteSurfaceProps } from '../navigation/desktopRouteModule';
import { NativeMemoriesPage, NativeMemoriesUnavailable } from './NativeMemoriesPage';
import {
  useNativeMemoriesRouteBinding,
  type NativeMemoriesRouteBinding,
} from './NativeMemoriesRouteContext';
import { createNativeMemoriesController } from './nativeMemoriesController';
import { createProjectMemoriesController } from './projectMemoriesController';

export function NativeMemoriesRouteSurface({ context }: DesktopRouteSurfaceProps) {
  const binding = useNativeMemoriesRouteBinding();
  if (
    !binding ||
    !binding.authority.available ||
    binding.authority.scope.authority !== 'local' ||
    context.tenantId !== binding.authority.scope.tenantId ||
    context.projectId !== binding.authority.scope.projectId
  )
    return <NativeMemoriesUnavailable />;
  return <BoundNativeMemoriesRoute binding={binding} />;
}

function BoundNativeMemoriesRoute({ binding }: Readonly<{ binding: NativeMemoriesRouteBinding }>) {
  const controllers = useMemo(() => {
    const list = createProjectMemoriesController({
      authority: 'local',
      client: binding.listClient,
      initialScope: binding.authority.scope,
    });
    const editor = createNativeMemoriesController({
      client: binding.client,
      authority: binding.authority,
      onAccepted: () => {
        if (binding.authority.allowedActions.includes('list')) void list.retry();
      },
    });
    return { list, editor };
  }, [binding]);
  const list = useSyncExternalStore(
    controllers.list.subscribe,
    controllers.list.getSnapshot,
    controllers.list.getSnapshot,
  );
  const editor = useSyncExternalStore(
    controllers.editor.subscribe,
    controllers.editor.getSnapshot,
    controllers.editor.getSnapshot,
  );
  useLayoutEffect(() => {
    controllers.editor.activate();
    if (controllers.editor.getSnapshot().allowedActions.includes('list'))
      void controllers.list.load(binding.authority.scope);
    return () => {
      controllers.editor.stop();
      controllers.list.stop();
    };
  }, [binding, controllers]);
  return (
    <NativeMemoriesPage
      list={list}
      editor={editor}
      controller={controllers.editor}
      onReload={() => {
        if (controllers.editor.getSnapshot().allowedActions.includes('list'))
          void controllers.list.retry();
      }}
      onPageChange={(page) => {
        if (controllers.editor.getSnapshot().allowedActions.includes('list'))
          void controllers.list.goToPage(page);
      }}
    />
  );
}
