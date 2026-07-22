import { useTranslation } from 'react-i18next';
import { Navigate, useParams } from 'react-router-dom';

import { useAuthStore } from '@/stores/auth';
import { useTenantStore } from '@/stores/tenant';

import { buildWorkspaceBlackboardRedirectQuery } from '@/pages/project/blackboardRouteUtils';

export function WorkspaceBlackboardRedirect() {
  const { t } = useTranslation();
  const {
    tenantId: tenantIdParam,
    projectId,
    workspaceId,
  } = useParams<{
    tenantId?: string;
    projectId?: string;
    workspaceId?: string;
  }>();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const user = useAuthStore((state) => state.user);
  const tenantId = tenantIdParam ?? currentTenant?.id ?? user?.tenant_id;

  // Wait for both ids rather than navigating to a malformed `/project//blackboard` URL.
  if (!tenantId || !projectId) {
    return (
      <div
        className="flex min-h-[240px] items-center justify-center text-sm text-zinc-500"
        role="status"
      >
        {t('common.loading', 'Loading…')}
      </div>
    );
  }

  const query = buildWorkspaceBlackboardRedirectQuery(workspaceId);

  return (
    <Navigate
      to={`/tenant/${tenantId}/project/${projectId}/blackboard${query ? `?${query}` : ''}`}
      replace
    />
  );
}
