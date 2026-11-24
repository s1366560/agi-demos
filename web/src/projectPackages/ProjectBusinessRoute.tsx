import { useSyncExternalStore, type ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { useProjectStore } from '@/stores/project';

import { getAuthToken, subscribeCloudIdentity } from '@/utils/tokenResolver';

import { RichPackagePages } from '../../../agi-stack/packages/plugin-marketplace-ui/src/RichPackagePages';

import { businessRouteScope } from './businessLocation';
import { useWebPackageSession } from './useWebPackageSession';

export function ProjectBusinessRoute({ children }: { children: ReactNode }) {
  const { pathname, search } = useLocation();
  const current = useProjectStore((state) => state.currentProject);
  const selected = businessRouteScope(pathname, new URLSearchParams(search), current);
  const token = useSyncExternalStore(subscribeCloudIdentity, getAuthToken);
  const session = useWebPackageSession(token);
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  if (!selected || !token) return children;
  const { tenant, project, plugin } = selected;
  const query = new URLSearchParams({ projectId: project });
  if (plugin) query.set('marketPlugin', plugin);
  const market = {
    pathname: '/tenant/' + encodeURIComponent(tenant) + '/plugins',
    search: query.toString(),
  };
  return (
    <RichPackagePages
      key={JSON.stringify([tenant, project, plugin, token])}
      scope={{ tenantId: tenant, projectId: project }}
      target="web"
      locale={i18n.language}
      pathname={pathname}
      {...(plugin ? { pluginId: plugin } : {})}
      backToMarket={<Link to={market}>{t('tenant.pluginHub.backToMarket')}</Link>}
      unmatched={plugin ? <Link to={market}>{t('tenant.pluginHub.backToMarket')}</Link> : children}
      transport={session.transport}
      streamCommand={session.stream}
      navigate={(path, options) => {
        const next = new URLSearchParams({ tenant, project });
        if (options?.pluginId ?? plugin)
          next.set('businessPackage', (options?.pluginId ?? plugin)!);
        void navigate({ pathname: path, search: next.toString() }, options);
      }}
    />
  );
}
