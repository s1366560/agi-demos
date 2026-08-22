import { useEffect, useState, type FC } from 'react';

import { Navigate, useLocation, useParams } from 'react-router-dom';

import { useAuthStore } from '../../stores/auth';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';
import { buildAgentWorkspacePath } from '../../utils/agentWorkspacePath';

export const ProjectChannelsRedirect: FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const user = useAuthStore((state) => state.user);
  const tenantId = currentTenant?.id || user?.tenant_id;
  const basePath = tenantId ? `/tenant/${tenantId}/plugins` : '/tenant/plugins';
  const projectQuery = projectId ? `?projectId=${encodeURIComponent(projectId)}` : '';

  return <Navigate to={`${basePath}${projectQuery}`} replace />;
};

export const LegacyTenantAuditLogsRedirect: FC = () => {
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const user = useAuthStore((state) => state.user);
  const tenantId = currentTenant?.id || user?.tenant_id;

  return (
    <Navigate to={tenantId ? `/tenant/${tenantId}/audit-logs` : '/tenant/audit-logs'} replace />
  );
};

function buildCanonicalProjectRedirectPath({
  tenantId,
  projectId,
  rest,
  query,
}: {
  tenantId: string;
  projectId?: string | undefined;
  rest?: string | undefined;
  query?: string | undefined;
}): string {
  const subPath = rest ? `/${rest}` : '';
  const normalizedQuery = query || '';
  return `/tenant/${tenantId}/project/${projectId ?? ''}${subPath}${normalizedQuery}`;
}

function buildTenantProjectsFallbackPath(tenantId: string | undefined, query: string): string {
  return tenantId ? `/tenant/${tenantId}/projects${query}` : `/tenant/projects${query}`;
}

function useResolvedProjectRedirectPath({
  projectId,
  rest,
  query,
}: {
  projectId?: string | undefined;
  rest?: string | undefined;
  query?: string | undefined;
}): string | null {
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenants = useTenantStore((state) => state.tenants);
  const listTenants = useTenantStore((state) => state.listTenants);
  const user = useAuthStore((state) => state.user);
  const projects = useProjectStore((state) => state.projects);
  const getProject = useProjectStore((state) => state.getProject);
  const [resolvedPath, setResolvedPath] = useState<string | null>(null);
  const normalizedQuery = query || '';
  const fallbackTenantId = currentTenant?.id || user?.tenant_id || tenants[0]?.id;
  const fallbackPath = buildTenantProjectsFallbackPath(fallbackTenantId, normalizedQuery);

  useEffect(() => {
    let cancelled = false;

    if (!projectId) {
      return () => {
        cancelled = true;
      };
    }

    const trustedTenantId =
      currentTenant?.id &&
      projects.some((project) => project.id === projectId && project.tenant_id === currentTenant.id)
        ? currentTenant.id
        : undefined;
    const uniqueTenantIds = (tenantIds: Array<string | undefined>) =>
      tenantIds.filter(
        (tenantId, index, values): tenantId is string =>
          Boolean(tenantId) && values.indexOf(tenantId) === index
      );
    let candidateTenantIds = uniqueTenantIds([
      trustedTenantId,
      currentTenant?.id,
      user?.tenant_id,
      ...tenants.map((tenant) => tenant.id),
    ]);

    const resolvePath = async () => {
      if (trustedTenantId) {
        return buildCanonicalProjectRedirectPath({
          tenantId: trustedTenantId,
          projectId,
          rest,
          query: normalizedQuery,
        });
      }

      if (candidateTenantIds.length === 0) {
        try {
          await listTenants();
          candidateTenantIds = uniqueTenantIds(
            useTenantStore.getState().tenants.map((tenant) => tenant.id)
          );
        } catch {
          return fallbackPath;
        }
      }

      for (const tenantId of candidateTenantIds) {
        try {
          await getProject(tenantId, projectId);
          return buildCanonicalProjectRedirectPath({
            tenantId,
            projectId,
            rest,
            query: normalizedQuery,
          });
        } catch {
          // Try the next candidate tenant resolution path.
        }
      }

      return buildTenantProjectsFallbackPath(
        candidateTenantIds[0] ?? fallbackTenantId,
        normalizedQuery
      );
    };

    void resolvePath().then((path) => {
      if (!cancelled) {
        setResolvedPath(path);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [
    currentTenant?.id,
    fallbackPath,
    fallbackTenantId,
    getProject,
    listTenants,
    normalizedQuery,
    projectId,
    projects,
    rest,
    tenants,
    user?.tenant_id,
  ]);

  return projectId ? resolvedPath : fallbackPath;
}

function getLegacyWorkspaceRedirectParams(search: string): {
  projectId?: string | undefined;
  workspaceId: string | null;
} {
  const searchParams = new URLSearchParams(search);

  return {
    projectId: searchParams.get('projectId') ?? undefined,
    workspaceId: searchParams.get('workspaceId'),
  };
}

export const LegacyProjectRedirect: FC = () => {
  const { projectId, '*': rest } = useParams();
  const location = useLocation();
  const resolvedPath = useResolvedProjectRedirectPath({
    projectId,
    rest,
    query: location.search || '',
  });

  if (!resolvedPath) {
    return null;
  }

  return <Navigate to={resolvedPath} replace />;
};

export const GenericTenantProjectRedirect = LegacyProjectRedirect;

export const LegacyTenantWorkspaceRedirect: FC = () => {
  const { tenantId } = useParams<{ tenantId: string }>();
  const location = useLocation();
  const { projectId, workspaceId } = getLegacyWorkspaceRedirectParams(location.search);

  return (
    <Navigate
      to={buildAgentWorkspacePath({
        tenantId,
        projectId,
        workspaceId,
      })}
      replace
    />
  );
};

function isUuidPathSegment(segment: string | undefined): boolean {
  return Boolean(
    segment?.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
  );
}

export const LegacyTenantSingleSegmentRedirect: FC = () => {
  const { segment } = useParams<{ segment: string }>();
  const location = useLocation();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenants = useTenantStore((state) => state.tenants);
  const { projectId, workspaceId } = getLegacyWorkspaceRedirectParams(location.search);
  const isAccessibleTenant =
    Boolean(segment) &&
    (segment === currentTenant?.id ||
      tenants.some((tenant) => tenant.id === segment) ||
      isUuidPathSegment(segment));

  if (!segment) {
    return <Navigate to="/tenant" replace />;
  }

  if (isAccessibleTenant) {
    return <Navigate to={`/tenant/${segment}/overview`} replace />;
  }

  return (
    <Navigate
      to={buildAgentWorkspacePath({
        conversationId: segment,
        projectId,
        workspaceId,
      })}
      replace
    />
  );
};

export const LegacyTenantConversationRedirect: FC = () => {
  const { tenantId, conversation } = useParams<{ tenantId: string; conversation: string }>();
  const location = useLocation();
  const { projectId, workspaceId } = getLegacyWorkspaceRedirectParams(location.search);

  return (
    <Navigate
      to={buildAgentWorkspacePath({
        tenantId,
        conversationId: conversation,
        projectId,
        workspaceId,
      })}
      replace
    />
  );
};
