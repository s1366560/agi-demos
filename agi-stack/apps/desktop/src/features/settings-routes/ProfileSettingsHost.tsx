import { useEffect, useState } from 'react';

import { useI18n } from '../../i18n';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopRouteModule,
  DesktopRouteModuleLoader,
} from '../navigation/desktopRouteModule';
import { PROFILE_ROUTE_ID } from './profileRoutePresentationModel';

export function ProfileSettingsHost({
  config,
  loader,
}: Readonly<{
  config: DesktopRuntimeConfig;
  loader: DesktopRouteModuleLoader;
}>) {
  const { t } = useI18n();
  const [module, setModule] = useState<DesktopRouteModule | null>(null);
  const [reasonCode, setReasonCode] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setModule(null);
    setReasonCode(null);
    void loader()
      .then((loaded) => {
        if (!active) return;
        if (
          loaded.routeId !== PROFILE_ROUTE_ID ||
          loaded.capability !== PROFILE_ROUTE_ID ||
          loaded.disposition !== 'implemented'
        ) {
          setReasonCode('user_profile_module_contract_invalid');
          return;
        }
        setModule(loaded);
      })
      .catch(() => {
        if (active) setReasonCode('user_profile_module_load_failed');
      });
    return () => {
      active = false;
    };
  }, [config.mode, loader]);

  if (reasonCode) return <code role="alert">{reasonCode}</code>;
  if (!module) return <div role="status">{t('common.loading')}</div>;
  const Surface = module.Surface;
  return (
    <Surface
      module={module}
      context={{
        tenantId: config.tenantId || undefined,
        projectId: config.projectId || undefined,
        workspaceId: config.workspaceId || undefined,
      }}
    />
  );
}
