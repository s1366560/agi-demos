import { openVoiceSocket } from './voiceSocket';
import { RichPackagePages } from './DesktopRichPackagePages';
import { devicePageCall } from './device';
import { transport, streamCommand } from './transport';
import type { SignedWorkbench } from './useSignedWorkbench';

import { PackageManagement } from './PackageManagement';
import { messages } from './messages';
import './workbench.css';

export type DesktopPackageWorkbenchProps = {
  workbench: SignedWorkbench;
  tenant: string;
  project: string | null;
  locale: string;
  onChanged?: () => void;
};

export function DesktopPackageWorkbench({
  workbench,
  tenant,
  project,
  locale,
  onChanged,
}: DesktopPackageWorkbenchProps) {
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
        <PackageManagement tenant={tenant} project={project} full canManage locale={locale} refresh={onChanged} />
      ) : (
        <RichPackagePages
          scope={{ tenantId: tenant, projectId: workbench.route.projectId }}
          pluginId={workbench.route.pluginId}
          pathname={workbench.address}
          target="desktop-renderer"
          locale={locale}
          transport={transport}
          openVoiceSocket={openVoiceSocket}
          streamCommand={streamCommand}
          invokeDevice={
            workbench.route.projectId
              ? devicePageCall(tenant, workbench.route.projectId)
              : undefined
          }
          navigate={(path, options) => {
            const hash = '#' + path;
            if (options?.replace) window.location.replace(hash);
            else window.location.hash = hash;
          }}
        />
      )}
    </main>
  );
}
