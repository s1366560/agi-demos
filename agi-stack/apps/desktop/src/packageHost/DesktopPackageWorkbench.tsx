import { useSyncExternalStore } from 'react';

import { PackageManagement } from './PackageManagement';
import { messages } from './messages';
import './workbench.css';

const locationHash = () => window.location.hash;
function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}

export function useSignedWorkbench(tenant: string) {
  const hash = useSyncExternalStore(subscribe, locationHash).slice(1);
  return Boolean(tenant) && hash.split('?', 1)[0] === '/tenant/' + encodeURIComponent(tenant) + '/plugins';
}

export function DesktopPackageWorkbench({
  tenant,
  project,
  locale,
}: {
  tenant: string;
  project: string | null;
  locale: string;
}) {
  return (
    <main className="desktop-package-workbench">
      <button type="button" onClick={() => { window.location.hash = ''; }}>
        {messages.backToWorkspace}
      </button>
      <PackageManagement tenant={tenant} project={project} full canManage locale={locale} />
    </main>
  );
}
