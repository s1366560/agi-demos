import { useCallback, useMemo, useSyncExternalStore } from 'react';
import { createMarketplaceClient } from '../../../../packages/plugin-marketplace-ui/src/client';
import { marketText } from '../../../../packages/plugin-marketplace-ui/src/pluginMarketText';
import type { Installation } from '../../../../packages/plugin-marketplace-ui/src/pluginMarketTypes';
import { CloudBusinessPage } from '../features/settings/CloudBusinessPage';
import { PluginMarket } from '../../../../packages/plugin-marketplace-ui/src/PluginMarket';
import { RichPackagePages } from '../../../../packages/plugin-marketplace-ui/src/RichPackagePages';
import { pluginArchiveBase64 } from '../api/localPluginClient';
import { openFilesWithDesktopDialog } from '../features/runtime/nativeFileBridge';
import { DevicePluginSettings } from '../features/settings/DevicePluginSettings';
import { devicePageCall } from './device';
import { messages as t } from './messages';
import { packages, streamCommand, transport } from './transport';

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
  full = false,
  locale = document.documentElement.lang,
}: {
  tenant: string;
  project: string;
  canManage: boolean;
  refresh?: () => void;
  full?: boolean;
  locale?: string;
}) {
  const marketplace = useMemo(
    () => createMarketplaceClient(transport, { tenant_id: tenant, project_id: project }),
    [tenant, project],
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
  const hash = useSyncExternalStore(subscribe, currentLocation).slice(1);
  const base = full ? '/tenant/' + encodeURIComponent(tenant) + '/plugins' : '/plugins';
  const index = hash.indexOf('?');
  const pathname = index < 0 ? hash : hash.slice(0, index);
  const params = new URLSearchParams(index < 0 ? '' : hash.slice(index + 1));
  const plugin = pathname === base ? params.get('marketPlugin') : null;
  const page = full && pathname === base ? params.get('marketPage') : null;
  const navigate = (id: string | null, path?: string) => {
    const query = pathname === base ? new URLSearchParams(params) : new URLSearchParams();
    if (id) query.set('marketPlugin', id);
    else query.delete('marketPlugin');
    if (path) query.set('marketPage', path);
    else query.delete('marketPage');
    const search = query.toString();
    window.location.hash = base + (search ? '?' + search : '');
  };
  const open = (path: string) => {
    if (full) navigate(plugin, path);
    else window.location.hash = path;
  };
  const device = useCallback(
    (pluginId: string, digest: string | null, release?: NpmRelease) => (
      <DevicePluginSettings
        key={JSON.stringify([tenant, project, pluginId, digest])}
        tenant={tenant}
        project={project}
        pluginId={pluginId}
        digest={digest}
        loadArchive={
          release && canManage
            ? async () => {
                const result = await transport<{ archive_base64: string; digest: string }>(
                  packages + '/npm/resolve',
                  {
                    method: 'POST',
                    body: {
                      tenant_id: tenant,
                      project_id: project,
                      package_name: release.packageName,
                      version: release.version,
                    },
                  },
                );
                if (!digest || result.digest !== digest)
                  throw new Error('device_plugin_release_changed');
                return result.archive_base64;
              }
            : undefined
        }
      />
    ),
    [tenant, project, canManage],
  );
  if (page)
    return (
      <>
        <button type="button" onClick={() => navigate(plugin)}>
          {t.backToMarket}
        </button>
        <RichPackagePages
          scope={{ tenantId: tenant, projectId: project }}
          target="desktop-renderer"
          pathname={page}
          navigate={open}
          locale={locale}
          transport={transport}
          streamCommand={streamCommand}
          invokeDevice={devicePageCall(tenant, project)}
        />
      </>
    );
  return (
    <PluginMarket
      key={JSON.stringify([tenant, project])}
      tenantId={tenant}
      projectId={project}
      target="desktop-renderer"
      transport={transport}
      canManage={canManage}
      locale={locale}
      pluginId={plugin}
      onSelect={(id) => navigate(id)}
      onOpen={open}
      importArchive={importArchive}
      deviceSettings={device}
      declarativePage={declarativePage}
      onChanged={refresh}
    />
  );
}
