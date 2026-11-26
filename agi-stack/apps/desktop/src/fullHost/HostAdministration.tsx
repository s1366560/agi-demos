import { useMemo } from 'react';
import type { CloudSessionProjection } from '../api/cloudSessionProjectionClient';
import { initialDesktopRuntimeConfig } from '../features/auth/loginRuntimeModel';
import { createDesktopTenantAuditHttpProjectionV2 } from '../plugins/desktopTenantAuditHttpProjectionV2';
import { createDesktopTenantGovernanceHttpProjectionV2 } from '../plugins/desktopTenantGovernanceHttpProjectionV2';
import { createDesktopTenantOrganizationSettingsHttpProjectionV2 } from '../plugins/desktopTenantOrganizationSettingsHttpProjectionV2';
import { createDesktopTenantSettingsHttpProjectionV2 } from '../plugins/desktopTenantSettingsHttpProjectionV2';
import { TenantAuditPage } from '../features/tenant-admin/TenantAuditPage';
import { createTenantAuditController } from '../features/tenant-admin/tenantAuditController';
import { TenantGovernancePage } from '../features/tenant-admin/TenantGovernancePage';
import { createTenantGovernanceController } from '../features/tenant-admin/tenantGovernanceController';
import { TenantOrganizationSettingsPage } from '../features/tenant-admin/TenantOrganizationSettingsPage';
import { createTenantOrganizationSettingsController } from '../features/tenant-admin/tenantOrganizationSettingsController';
import { TenantSettingsPage } from '../features/tenant-admin/TenantSettingsPage';
import { createTenantSettingsController } from '../features/tenant-admin/tenantSettingsController';
import { useTenantAdminController } from '../features/tenant-admin/useTenantAdminController';
import { useTenantManagementController } from '../features/tenant-admin/useTenantManagementController';
import type { DesktopRuntimeConfig } from '../types';
import { ProjectDirectory } from './ProjectDirectory';
import type { HostSection } from './workbenchModel';

function cloudConfig(tenant: string, project: string | null): DesktopRuntimeConfig {
  return {
    ...initialDesktopRuntimeConfig(),
    mode: 'cloud',
    tenantId: tenant,
    projectId: project ?? '',
    apiKey: '',
  };
}

function UsersSection({ tenant, project }: { tenant: string; project: string | null }) {
  const config = useMemo(() => cloudConfig(tenant, project), [tenant, project]);
  const scope = useMemo(() => ({ authority: 'cloud' as const, tenantId: tenant }), [tenant]);
  const controller = useMemo(
    () =>
      createTenantGovernanceController({
        client: createDesktopTenantGovernanceHttpProjectionV2(config),
        initialScope: scope,
      }),
    [config, scope],
  );
  const { model, retry } = useTenantAdminController(controller, scope);
  return (
    <main className="desktop-host-administration">
      <TenantGovernancePage model={model} controller={controller} onRetry={retry} />
    </main>
  );
}

function AuditSection({ tenant, project }: { tenant: string; project: string | null }) {
  const config = useMemo(() => cloudConfig(tenant, project), [tenant, project]);
  const scope = useMemo(() => ({ authority: 'cloud' as const, tenantId: tenant }), [tenant]);
  const controller = useMemo(
    () =>
      createTenantAuditController({
        client: createDesktopTenantAuditHttpProjectionV2(config),
        initialScope: scope,
      }),
    [config, scope],
  );
  const { model, retry } = useTenantAdminController(controller, scope);
  return (
    <main className="desktop-host-administration">
      <TenantAuditPage model={model} controller={controller} onRetry={retry} />
    </main>
  );
}

function OrganizationSection({ tenant, project }: { tenant: string; project: string | null }) {
  const config = useMemo(() => cloudConfig(tenant, project), [tenant, project]);
  const scope = useMemo(() => ({ authority: 'cloud' as const, tenantId: tenant }), [tenant]);
  const controller = useMemo(
    () =>
      createTenantOrganizationSettingsController({
        client: createDesktopTenantOrganizationSettingsHttpProjectionV2(config),
        initialScope: scope,
      }),
    [config, scope],
  );
  const { model, retry } = useTenantManagementController(controller, scope);
  return (
    <main className="desktop-host-administration">
      <TenantOrganizationSettingsPage model={model} controller={controller} onRetry={retry} />
    </main>
  );
}

function SettingsSection({ tenant, project }: { tenant: string; project: string | null }) {
  const config = useMemo(() => cloudConfig(tenant, project), [tenant, project]);
  const scope = useMemo(() => ({ authority: 'cloud' as const, tenantId: tenant }), [tenant]);
  const controller = useMemo(
    () =>
      createTenantSettingsController({
        client: createDesktopTenantSettingsHttpProjectionV2(config),
        initialScope: scope,
      }),
    [config, scope],
  );
  const { model, retry } = useTenantManagementController(controller, scope);
  return (
    <main className="desktop-host-administration">
      <TenantSettingsPage model={model} controller={controller} onRetry={retry} />
    </main>
  );
}

export function HostAdministration({
  section,
  tenant,
  project,
  session,
  reload,
}: {
  section: HostSection;
  tenant: string;
  project: string | null;
  session: CloudSessionProjection | null;
  reload(): Promise<void>;
}) {
  if (section === 'projects') {
    return <ProjectDirectory session={session} tenant={tenant} reload={reload} />;
  }
  if (section === 'users') return <UsersSection tenant={tenant} project={project} />;
  if (section === 'audit-logs') return <AuditSection tenant={tenant} project={project} />;
  if (section === 'org-settings') return <OrganizationSection tenant={tenant} project={project} />;
  if (section === 'settings') return <SettingsSection tenant={tenant} project={project} />;
  return null;
}
