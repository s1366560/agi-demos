import { cloudMemoriesEnUS, cloudMemoriesZhCN } from '@business/knowledge/ui/desktop/project-knowledge/locales/cloudMemoriesMessages';
import { I18nContext, useI18n } from '../../i18nContext';
import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';
import type { DesktopRouteSurfaceProps } from '../navigation/desktopRouteModule';
import {
  useCloudMemoryRouteBinding,
  type CloudMemoryRouteBinding,
} from './CloudMemoryRouteContext';
import { createCloudMemoriesController } from '@business/knowledge/ui/desktop/project-knowledge/cloudMemoriesController';
import { CloudMemoriesPage, CloudMemoriesUnavailable } from '@business/knowledge/ui/desktop/project-knowledge/CloudMemoriesPage';
import './CloudMemoriesPage.css';

export function CloudMemoryRouteSurface({ context }: DesktopRouteSurfaceProps) {
  const messages = useI18n(cloudMemoriesEnUS, cloudMemoriesZhCN);
  return <I18nContext.Provider value={messages}><ScopedCloudMemories context={context} /></I18nContext.Provider>;
}

function ScopedCloudMemories({ context }: Pick<DesktopRouteSurfaceProps, 'context'>) {
  const binding = useCloudMemoryRouteBinding();
  if (
    !binding ||
    !binding.authority.available ||
    binding.authority.scope.authority !== 'cloud' ||
    binding.authority.scope.tenantId !== context.tenantId ||
    binding.authority.scope.projectId !== context.projectId
  )
    return <CloudMemoriesUnavailable />;
  return <BoundCloudMemoriesRoute binding={binding} />;
}
function BoundCloudMemoriesRoute({ binding }: Readonly<{ binding: CloudMemoryRouteBinding }>) {
  const controller = useMemo(() => createCloudMemoriesController(binding), [binding]);
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useLayoutEffect(() => {
    controller.activate();
    void controller.loadPage();
    return () => controller.stop();
  }, [controller]);
  return <CloudMemoriesPage model={model} controller={controller} />;
}
