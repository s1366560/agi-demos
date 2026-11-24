import { useSyncExternalStore } from 'react';

import { PackageManagement } from './PackageManagement';
import './workbench.css';

const locationHash = () => window.location.hash;
function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}

export function useSignedWorkbench(tenant: string) {
  const hash = useSyncExternalStore(subscribe, locationHash).slice(1);
  const separator = hash.indexOf('?');
  if (
    !tenant ||
    separator < 0 ||
    hash.slice(0, separator) !== '/tenant/' + encodeURIComponent(tenant) + '/plugins'
  )
    return false;
  const query = new URLSearchParams(hash.slice(separator + 1));
  return Boolean(query.get('marketPlugin') && query.get('marketPage'));
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
      <PackageManagement tenant={tenant} project={project} full canManage locale={locale} />
    </main>
  );
}
