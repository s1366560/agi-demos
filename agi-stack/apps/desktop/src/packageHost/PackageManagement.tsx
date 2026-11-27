import { openVoiceSocket } from './voiceSocket';
import { installationDestination } from '../../../../packages/plugin-marketplace-ui/src/installationReturn';
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import {
  fullMarketProjectId,
  loadTenantProjects,
  type CatalogProject,
} from '../fullHost/projectCatalog';
import { createMarketplaceClient } from '../../../../packages/plugin-marketplace-ui/src/client';
import { marketText } from '../../../../packages/plugin-marketplace-ui/src/pluginMarketText';
import {
  npmResourcePath,
  type Installation,
} from '../../../../packages/plugin-marketplace-ui/src/pluginMarketTypes';
import { CloudBusinessPage } from '../features/settings/CloudBusinessPage';
import { PluginMarket } from '../../../../packages/plugin-marketplace-ui/src/PluginMarket';
import { RichPackagePages } from './DesktopRichPackagePages';
import { pluginArchiveBase64 } from '../api/localPluginClient';
import { openFilesWithDesktopDialog } from '../features/runtime/nativeFileBridge';
import { DevicePluginSettings } from '../features/settings/DevicePluginSettings';
import { devicePageCall } from './device';
import { messages as t } from './messages';
import { streamCommand, transport } from './transport';

const currentLocation = () => window.location.hash;
function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}
async function importArchive() {
  const files = await openFilesWithDesktopDialog('plugin_package');
  if (files.status === 'cancelled') return null;
  if (files.files.length !== 1 || !files.files[0]) throw new Error('device_plugin_archive_invalid');
  return pluginArchiveBase64(files.files[0]);
}

type NpmRelease = { packageName: string; version: string };

export function PackageManagement({
  tenant,
  project,
  canManage,
  refresh,
  onNavigate,
  full = false,
  locale = document.documentElement.lang,
}: {
  tenant: string;
  project: string | null;
  canManage: boolean;
  refresh?: () => void;
  onNavigate?: () => void;
  full?: boolean;
  locale?: string;
}) {
  const hash = useSyncExternalStore(subscribe, currentLocation).slice(1);
  const base = full ? '/tenant/' + encodeURIComponent(tenant) + '/plugins' : '/plugins';
  const index = hash.indexOf('?');
  const pathname = index < 0 ? hash : hash.slice(0, index);
  const params = new URLSearchParams(index < 0 ? '' : hash.slice(index + 1));
  const requestedProject = full
    ? fullMarketProjectId(index < 0 ? '' : hash.slice(index + 1))
    : null;
  const tenantOnly = full
    ? !requestedProject
    : project === null || (pathname === base && params.get('marketScope') === 'tenant');
  const scopeProject = full ? requestedProject : tenantOnly ? null : project;
  const [catalog, setCatalog] = useState<CatalogProject[]>([]);
  const [catalogError, setCatalogError] = useState('');
  useEffect(() => {
    if (!full || !tenant) return;
    const controller = new AbortController();
    void loadTenantProjects(transport, tenant, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) {
          setCatalog(items);
          setCatalogError('');
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setCatalog([]);
          setCatalogError(String(cause));
        }
      });
    return () => controller.abort();
  }, [full, tenant]);
  function chooseScope(next: string) {
    const query = pathname === base ? new URLSearchParams(params) : new URLSearchParams();
    if (next) query.set('projectId', next);
    else query.delete('projectId');
    query.delete('marketScope');
    query.delete('marketPage');
    query.delete('marketPlugin');
    query.delete('optionalPlugin');
    const search = query.toString();
    onNavigate?.();
    window.location.hash = base + (search ? '?' + search : '');
  }
  const marketplace = useMemo(
    () =>
      createMarketplaceClient(
        transport,
        scopeProject ? { tenant_id: tenant, project_id: scopeProject } : { tenant_id: tenant },
      ),
    [tenant, scopeProject],
  );
  const declarativePage = (installation: Installation, canExecute: boolean) =>
    installation.actual_digest && (
      <CloudBusinessPage
        key={installation.actual_digest}
        client={marketplace}
        item={installation}
        digest={installation.actual_digest}
        label={marketText(locale).open}
        canExecute={canExecute}
      />
    );
  const plugin = pathname === base ? params.get('marketPlugin') : null;
  const page = pathname === base ? params.get('marketPage') : null;
  const navigate = (id: string | null, path?: string, replace = false) => {
    const query = pathname === base ? new URLSearchParams(params) : new URLSearchParams();
    if (id) query.set('marketPlugin', id);
    else query.delete('marketPlugin');
    if (path) query.set('marketPage', path);
    else query.delete('marketPage');
    const search = query.toString();
    const destination = base + (search ? '?' + search : '');
    onNavigate?.();
    if (replace) window.location.replace('#' + destination);
    else window.location.hash = destination;
  };
  const open = (path: string, options?: { pluginId?: string; replace?: boolean }) => {
    if (full || tenantOnly) navigate(options?.pluginId ?? plugin, path, options?.replace);
    else if (options?.replace) window.location.replace('#' + path);
    else window.location.hash = path;
  };
  const device = useCallback(
    (pluginId: string, digest: string | null, release?: NpmRelease) =>
      scopeProject && (
        <DevicePluginSettings
          key={JSON.stringify([tenant, scopeProject, pluginId, digest])}
          tenant={tenant}
          project={scopeProject}
          pluginId={pluginId}
          digest={digest}
          loadArchive={
            release && canManage
              ? async () => {
                  const result = await transport<{
                    archive_base64: string;
                    digest: string;
                  }>(npmResourcePath(scopeProject, 'resolve'), {
                    method: 'POST',
                    body: {
                      tenant_id: tenant,
                      project_id: scopeProject,
                      package_name: release.packageName,
                      version: release.version,
                    },
                  });
                  if (!digest || result.digest !== digest)
                    throw new Error('device_plugin_release_changed');
                  return result.archive_base64;
                }
              : undefined
          }
        />
      ),
    [tenant, scopeProject, canManage],
  );
  if (page)
    return (
      <>
        <button type="button" onClick={() => navigate(plugin)}>
          {t.backToMarket}
        </button>
        <RichPackagePages
          scope={{ tenantId: tenant, projectId: scopeProject }}
          pluginId={plugin ?? undefined}
          target="desktop-renderer"
          pathname={page}
          navigate={open}
          locale={locale}
          transport={transport}
          openVoiceSocket={openVoiceSocket}
          streamCommand={streamCommand}
          invokeDevice={scopeProject ? devicePageCall(tenant, scopeProject) : undefined}
        />
      </>
    );
  return (
    <>
      <label className="package-market-scope">
        {t.installationScope}
        {full ? (
          <select value={scopeProject ?? ''} onChange={(event) => chooseScope(event.target.value)}>
            <option value="">{t.tenantScope}</option>
            {catalog.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
            {scopeProject && !catalog.some((item) => item.id === scopeProject) ? (
              <option value={scopeProject}>{scopeProject}</option>
            ) : null}
          </select>
        ) : (
          <select
            value={tenantOnly ? 'tenant' : 'project'}
            onChange={(event) => {
              onNavigate?.();
              window.location.hash =
                base + (event.target.value === 'tenant' ? '?marketScope=tenant' : '');
            }}
          >
            {project && <option value="project">{t.project}</option>}
            <option value="tenant">{t.tenant}</option>
          </select>
        )}
      </label>
      {catalogError ? <p role="alert">{catalogError}</p> : null}
      <PluginMarket
        key={JSON.stringify([tenant, scopeProject])}
        tenantId={tenant}
        projectId={scopeProject}
        target="desktop-renderer"
        transport={transport}
        canManage={canManage}
        locale={locale}
        pluginId={plugin}
        onSelect={(id) => navigate(id)}
        onOpen={open}
        importArchive={importArchive}
        deviceSettings={scopeProject ? device : undefined}
        declarativePage={scopeProject ? declarativePage : undefined}
        onActivated={(installation) => {
          const destination = installationDestination(
            params.get('returnTo'),
            { tenantId: tenant, projectId: scopeProject },
            installation,
            'desktop-renderer',
          );
          if (destination) window.location.replace('#' + destination);
        }}
        onChanged={refresh}
      />
    </>
  );
}
