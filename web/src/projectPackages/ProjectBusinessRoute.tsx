import { scopedPageLocation } from '../../../agi-stack/packages/plugin-slots/src/pageLocation';
import { useSyncExternalStore, type ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { useProjectStore } from '@/stores/project';

import { getAuthToken, subscribeCloudIdentity } from '@/utils/tokenResolver';

import { RichPackagePages } from '../../../agi-stack/packages/plugin-marketplace-ui/src/RichPackagePages';

import { businessRouteScope, tenantPageScope } from './businessLocation';
import { useWebPackageSession } from './useWebPackageSession';

export type FullWorkbenchMatcher = (
  pathname: string,
  scope: { tenant: string; project: string },
  current: { id: string; tenant_id: string } | null
) => boolean;

export function ProjectBusinessRoute({
  children,
  matchesFullRoute,
  insideWorkbench = false,
}: {
  children: ReactNode;
  insideWorkbench?: boolean;
  matchesFullRoute: FullWorkbenchMatcher;
}) {
  const { pathname, search, hash, state } = useLocation();
  const fromMarket = state?.fromPackageMarket === true;
  const showMarketNavigation = !insideWorkbench || fromMarket;
  // The workbench shell navigates its own pages; a marketplace review still offers the page menu.
  const showPageMenu = !insideWorkbench || fromMarket;
  const current = useProjectStore((state) => state.currentProject);
  const params = new URLSearchParams(search);
  const diagnostics = params.has('diagnostics');
  const selected = businessRouteScope(pathname, params, current);
  const token = useSyncExternalStore(subscribeCloudIdentity, getAuthToken);
  const session = useWebPackageSession(token);
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  if (!token) return children;
  const tenantOwner = tenantPageScope(pathname, params);
  const bookmark = pathname + search + hash;
  const install = (url: string) =>
    url + (url.includes('?') ? '&' : '?') + new URLSearchParams({ returnTo: bookmark });
  const fallback = selected ? projectPage(selected) : children;
  if (!tenantOwner) return fallback;
  const id = params.get('businessPackage');
  const market =
    '/tenant/' +
    encodeURIComponent(tenantOwner) +
    '/plugins' +
    (id ? '?' + new URLSearchParams({ marketPlugin: id }) : '');
  const back = <Link to={market}>{t('tenant.pluginHub.backToMarket')}</Link>;
  return (
    <RichPackagePages
      key={JSON.stringify([tenantOwner, id, token])}
      scope={{ tenantId: tenantOwner, projectId: null }}
      target="web"
      locale={i18n.language}
      pageMenu={showPageMenu}
      diagnostics={diagnostics}
      pathname={pathname + search + hash}
      {...(id ? { pluginId: id } : {})}
      backToMarket={showMarketNavigation ? back : null}
      unmatched={
        params.get('packageScope') === 'tenant' ? (
          <Link to={install(market)}>{t('tenant.pluginHub.backToMarket')}</Link>
        ) : (
          fallback
        )
      }
      transport={session.transport}
      openVoiceSocket={session.openVoiceSocket}
        streamCommand={session.stream}
      navigate={(path, options) => {
        const owner = options?.pluginId ?? id;
        const bindings = {
          tenant: tenantOwner,
          packageScope: 'tenant',
          ...(owner ? { businessPackage: owner } : {}),
        };
        void navigate(scopedPageLocation(path, bindings), { ...options, state });
      }}
    />
  );

  function projectPage(selected: NonNullable<ReturnType<typeof businessRouteScope>>) {
    const { tenant, project, plugin } = selected;
    const canOpenFull = matchesFullRoute(pathname, selected, current);
    if (canOpenFull && params.get('workbench') === 'full') return children;
    const fullQuery = new URLSearchParams(params);
    fullQuery.set('workbench', 'full');
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
        pageMenu={showPageMenu}
        diagnostics={diagnostics}
        pathname={pathname + search + hash}
        {...(plugin ? { pluginId: plugin } : {})}
        backToMarket={
          showMarketNavigation && (
            <>
              <Link to={market}>{t('tenant.pluginHub.backToMarket')}</Link>
              {canOpenFull && (
                <Link to={{ pathname, hash, search: fullQuery.toString() }}>
                  {t('tenant.pluginHub.openFullWorkbench')}
                </Link>
              )}
            </>
          )
        }
        unmatched={
          plugin ? (
            <Link to={install(market.pathname + '?' + market.search)}>
              {t('tenant.pluginHub.backToMarket')}
            </Link>
          ) : (
            children
          )
        }
        transport={session.transport}
        openVoiceSocket={session.openVoiceSocket}
        streamCommand={session.stream}
        navigate={(path, options) => {
          const next: Record<string, string> = { tenant, project };
          const owner = options?.pluginId ?? plugin;
          if (owner) next.businessPackage = owner;
          void navigate(scopedPageLocation(path, next), { ...options, state });
        }}
      />
    );
  }
}
