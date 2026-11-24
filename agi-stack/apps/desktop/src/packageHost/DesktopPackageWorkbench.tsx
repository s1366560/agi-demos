import { RichPackagePages } from '../../../../packages/plugin-marketplace-ui/src/RichPackagePages';
import { devicePageCall } from './device';
import { transport, streamCommand } from './transport';
import type { SignedWorkbench } from './useSignedWorkbench';

import { PackageManagement } from './PackageManagement';
import { messages } from './messages';
import './workbench.css';

export function DesktopPackageWorkbench({
  workbench,
  tenant,
  project,
  locale,
}: {
  workbench: SignedWorkbench;
  tenant: string;
  project: string | null;
  locale: string;
}) {
  return (
    <main className="desktop-package-workbench">
      <button
        type="button"
        onClick={() => {
          window.location.hash = '';
        }}
      >
        {messages.backToWorkspace}
      </button>
      {workbench.kind === 'market' ? (
        <PackageManagement tenant={tenant} project={project} full canManage locale={locale} />
      ) : (
        <RichPackagePages
          scope={{ tenantId: tenant, projectId: workbench.route.projectId }}
          pluginId={workbench.route.pluginId}
          pathname={workbench.address}
          target="desktop-renderer"
          locale={locale}
          transport={transport}
          streamCommand={streamCommand}
          invokeDevice={
            workbench.route.projectId
              ? devicePageCall(tenant, workbench.route.projectId)
              : undefined
          }
          navigate={(path, options) => {
            const scope = workbench.route.projectId ? 'project' : 'tenant';
            const query = new URLSearchParams({
              marketScope: scope,
              marketPlugin: workbench.route.pluginId,
              marketPage: path,
            });
            const hash = '#/tenant/' + encodeURIComponent(tenant) + '/plugins?' + query;
            if (options?.replace) window.location.replace(hash);
            else window.location.hash = hash;
          }}
        />
      )}
    </main>
  );
}
