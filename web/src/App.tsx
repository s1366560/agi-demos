import { lazy, Suspense, useEffect, useState, type ComponentType } from 'react';

import { Routes, Route, Navigate, useLocation, useParams, useSearchParams } from 'react-router-dom';

import { ErrorBoundary } from './components/common/ErrorBoundary';
import { OrgSetupGuard } from './components/common/OrgSetupGuard';
import { LazySpin } from './components/ui/lazyAntd';
import './i18n/config';
import { SchemaLayout } from './layouts/SchemaLayout';
import { TenantLayout } from './layouts/TenantLayout';
import { Login } from './pages/Login';
import { useAuthStore } from './stores/auth';
import { useProjectStore } from './stores/project';
import { useTenantStore } from './stores/tenant';
import { ThemeProvider } from './theme';
import { buildAgentWorkspacePath } from './utils/agentWorkspacePath';
import './App.css';

// ============================================================================
// CODE SPLITTING - Lazy load route components for better performance
// ============================================================================
// Components are loaded on-demand, reducing initial bundle size
// ============================================================================

// Auth pages
const ForceChangePassword = lazy(() =>
  import('./pages/ForceChangePassword').then((m) => ({ default: m.ForceChangePassword }))
);
const UserProfile = lazy(() =>
  import('./pages/UserProfile').then((m) => ({ default: m.UserProfile }))
);
const OAuthCallback = lazy(() =>
  import('./pages/OAuthCallback').then((m) => ({ default: m.OAuthCallback }))
);
const InviteAccept = lazy(() =>
  import('./pages/InviteAccept').then((m) => ({ default: m.InviteAccept }))
);
const DeviceApprove = lazy(() =>
  import('./pages/DeviceApprove').then((m) => ({ default: m.DeviceApprove }))
);

// Tenant pages
const TenantOverview = lazy(() =>
  import('./pages/tenant/TenantOverview').then((m) => ({
    default: m.TenantOverview,
  }))
);
const ProjectList = lazy(() =>
  import('./pages/tenant/ProjectList').then((m) => ({ default: m.ProjectList }))
);
const UserList = lazy(() =>
  import('./pages/tenant/UserList').then((m) => ({ default: m.UserList }))
);
const ProviderList = lazy(() =>
  import('./pages/tenant/ProviderList').then((m) => ({
    default: m.ProviderList,
  }))
);
const NewProject = lazy(() =>
  import('./pages/tenant/NewProject').then((m) => ({ default: m.NewProject }))
);
const EditProject = lazy(() =>
  import('./pages/tenant/EditProject').then((m) => ({ default: m.EditProject }))
);
const NewTenant = lazy(() =>
  import('./pages/tenant/NewTenant').then((m) => ({ default: m.NewTenant }))
);
const TenantSettings = lazy(() =>
  import('./pages/tenant/TenantSettings').then((m) => ({
    default: m.TenantSettings,
  }))
);
// Organization Settings
const OrgSettingsLayout = lazy(() =>
  import('./pages/tenant/org-settings/OrgSettingsLayout').then((m) => ({
    default: m.OrgSettingsLayout,
  }))
);
const OrgInfo = lazy(() =>
  import('./pages/tenant/org-settings/OrgInfo').then((m) => ({ default: m.OrgInfo }))
);
const OrgMembers = lazy(() =>
  import('./pages/tenant/org-settings/OrgMembers').then((m) => ({ default: m.OrgMembers }))
);
const OrgClusters = lazy(() =>
  import('./pages/tenant/org-settings/OrgClusters').then((m) => ({ default: m.OrgClusters }))
);
const OrgAudit = lazy(() =>
  import('./pages/tenant/org-settings/OrgAudit').then((m) => ({ default: m.OrgAudit }))
);
const OrgRegistry = lazy(() =>
  import('./pages/tenant/org-settings/OrgRegistry').then((m) => ({ default: m.OrgRegistry }))
);
const OrgSmtp = lazy(() =>
  import('./pages/tenant/org-settings/OrgSmtp').then((m) => ({ default: m.OrgSmtp }))
);
const OrgGenes = lazy(() =>
  import('./pages/tenant/org-settings/OrgGenes').then((m) => ({ default: m.OrgGenes }))
);
const TaskDashboard = lazy(() =>
  import('./pages/tenant/TaskDashboard').then((m) => ({
    default: m.TaskDashboard,
  }))
);
const AgentDashboard = lazy(() =>
  import('./pages/tenant/AgentDashboard').then((m) => ({
    default: m.AgentDashboard,
  }))
);
const WorkflowPatterns = lazy(() => import('./pages/tenant/WorkflowPatterns'));
const Analytics = lazy(() =>
  import('./pages/tenant/Analytics').then((m) => ({ default: m.Analytics }))
);
const Billing = lazy(() => import('./pages/tenant/Billing').then((m) => ({ default: m.Billing })));
const Events = lazy(() => import('./pages/tenant/Events').then((m) => ({ default: m.Events })));
const Webhooks = lazy(() =>
  import('./pages/tenant/Webhooks').then((m) => ({ default: m.Webhooks }))
);
const SubAgentList = lazy(() =>
  import('./pages/tenant/SubAgentList').then((m) => ({
    default: m.SubAgentList,
  }))
);
const SkillList = lazy(() =>
  import('./pages/tenant/SkillList').then((m) => ({ default: m.SkillList }))
);
const CuratedSkills = lazy(() => import('./pages/tenant/CuratedSkills'));
const AdminSkillReview = lazy(() => import('./pages/admin/AdminSkillReview'));
const TemplateMarketplace = lazy(() =>
  import('./pages/tenant/TemplateMarketplace').then((m) => ({
    default: m.TemplateMarketplace,
  }))
);
const PluginHub = lazy(() =>
  import('./pages/tenant/PluginHub').then((m) => ({
    default: m.PluginHub,
  }))
);
const McpServerList = lazy(() =>
  import('./components/mcp/McpServerListV2').then((m) => ({
    default: m.McpServerListV2,
  }))
);
const AgentDefinitions = lazy(() =>
  import('./pages/tenant/AgentDefinitions').then((m) => ({ default: m.AgentDefinitions }))
);
const AgentBindings = lazy(() =>
  import('./pages/tenant/AgentBindings').then((m) => ({ default: m.AgentBindings }))
);
const AgentWorkspace = lazy(() =>
  import('./pages/tenant/AgentWorkspace').then((m) => ({
    default: m.AgentWorkspace,
  }))
);
const WorkspaceList = lazy(() =>
  import('./pages/tenant/WorkspaceList').then((m) => ({ default: m.WorkspaceList }))
);
const WorkspaceCreate = lazy(() =>
  import('./pages/tenant/WorkspaceCreate').then((m) => ({ default: m.WorkspaceCreate }))
);
const WorkspaceBlackboardRedirect = lazy(() =>
  import('./pages/project/WorkspaceBlackboardRedirect').then((m) => ({
    default: m.WorkspaceBlackboardRedirect,
  }))
);
const InstanceList = lazy(() =>
  import('./pages/tenant/InstanceList').then((m) => ({ default: m.InstanceList }))
);
const InstanceLayout = lazy(() =>
  import('./pages/tenant/InstanceLayout').then((m) => ({ default: m.InstanceLayout }))
);
const InstanceOverview = lazy(() =>
  import('./pages/tenant/InstanceOverview').then((m) => ({ default: m.InstanceOverview }))
);
const CreateInstance = lazy(() =>
  import('./pages/tenant/CreateInstance').then((m) => ({ default: m.CreateInstance }))
);
const DeployProgress = lazy(() =>
  import('./pages/tenant/DeployProgress').then((m) => ({ default: m.DeployProgress }))
);
const ClusterList = lazy(() =>
  import('./pages/tenant/ClusterList').then((m) => ({ default: m.ClusterList }))
);
const ClusterDetail = lazy(() =>
  import('./pages/tenant/ClusterDetail').then((m) => ({ default: m.ClusterDetail }))
);
const GeneMarket = lazy(() =>
  import('./pages/tenant/GeneMarket').then((m) => ({ default: m.GeneMarket }))
);
const GeneDetail = lazy(() =>
  import('./pages/tenant/GeneDetail').then((m) => ({ default: m.GeneDetail }))
);
const InstanceTemplateList = lazy(() =>
  import('./pages/tenant/InstanceTemplateList').then((m) => ({
    default: m.InstanceTemplateList,
  }))
);
const InstanceMembers = lazy(() =>
  import('./pages/tenant/InstanceMembers').then((m) => ({ default: m.InstanceMembers }))
);
const InstanceSettings = lazy(() =>
  import('./pages/tenant/InstanceSettings').then((m) => ({ default: m.InstanceSettings }))
);
const InstanceGenes = lazy(() =>
  import('./pages/tenant/InstanceGenes').then((m) => ({ default: m.InstanceGenes }))
);
const InstanceChannels = lazy(() =>
  import('./pages/tenant/InstanceChannels').then((m) => ({ default: m.InstanceChannels }))
);
const InstanceFiles = lazy(() =>
  import('./pages/tenant/InstanceFiles').then((m) => ({ default: m.InstanceFiles }))
);
const AuditLogs = lazy(() =>
  import('./pages/tenant/AuditLogs').then((m) => ({ default: m.AuditLogs }))
);
const TrustPolicies = lazy(() =>
  import('./pages/tenant/TrustPolicies').then((m) => ({ default: m.TrustPolicies }))
);
const DecisionRecords = lazy(() =>
  import('./pages/tenant/DecisionRecords').then((m) => ({ default: m.DecisionRecords }))
);
const EvolutionLog = lazy(() =>
  import('./pages/tenant/EvolutionLog').then((m) => ({ default: m.EvolutionLog }))
);
const GenomeDetail = lazy(() =>
  import('./pages/tenant/GenomeDetail').then((m) => ({ default: m.GenomeDetail }))
);
const TemplateDetail = lazy(() =>
  import('./pages/tenant/TemplateDetail').then((m) => ({ default: m.TemplateDetail }))
);

// Admin pages
const PoolDashboard = lazy(() => import('./pages/admin/PoolDashboard'));

// Project pages
const ProjectOverview = lazy(() =>
  import('./pages/project/ProjectOverview').then((m) => ({
    default: m.ProjectOverview,
  }))
);
const MemoryList = lazy(() =>
  import('./pages/project/MemoryList').then((m) => ({ default: m.MemoryList }))
);
const NewMemory = lazy(() =>
  import('./pages/project/NewMemory').then((m) => ({ default: m.NewMemory }))
);
const MemoryDetail = lazy(() =>
  import('./pages/project/MemoryDetail').then((m) => ({
    default: m.MemoryDetail,
  }))
);
const MemoryGraph = lazy(() =>
  import('./pages/project/MemoryGraph').then((m) => ({
    default: m.MemoryGraph,
  }))
);
const EntitiesList = lazy(() =>
  import('./pages/project/EntitiesList').then((m) => ({
    default: m.EntitiesList,
  }))
);
const CommunitiesList = lazy(() =>
  import('./pages/project/CommunitiesList').then((m) => ({
    default: m.CommunitiesList as ComponentType,
  }))
);
const EnhancedSearch = lazy(() =>
  import('./pages/project/EnhancedSearch').then((m) => ({
    default: m.EnhancedSearch,
  }))
);
const Maintenance = lazy(() =>
  import('./pages/project/Maintenance').then((m) => ({
    default: m.Maintenance,
  }))
);
const CronJobs = lazy(
  () =>
    import('./pages/project/CronJobs').then((m) => ({ default: m.CronJobs })) as Promise<{
      default: React.ComponentType;
    }>
);
const Team = lazy(() => import('./pages/project/Team').then((m) => ({ default: m.Team })));
const ProjectSettings = lazy(() =>
  import('./pages/project/Settings').then((m) => ({
    default: m.ProjectSettings,
  }))
);
const Support = lazy(() => import('./pages/project/Support').then((m) => ({ default: m.Support })));
const Blackboard = lazy(() =>
  import('./pages/project/Blackboard').then((m) => ({ default: m.Blackboard }))
);

// Schema pages
const SchemaOverview = lazy(() => import('./pages/project/schema/SchemaOverview'));
const EntityTypeList = lazy(() => import('./pages/project/schema/EntityTypeList'));
const EdgeTypeList = lazy(() => import('./pages/project/schema/EdgeTypeList'));
const EdgeMapList = lazy(() => import('./pages/project/schema/EdgeMapList'));

// Loading fallback for lazy-loaded components
// Hoisted outside component to avoid recreation on each render
const PageLoader: React.FC = () => (
  <div className="flex items-center justify-center h-50">
    <LazySpin size="large" />
  </div>
);

const ProjectChannelsRedirect: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const user = useAuthStore((state) => state.user);
  const tenantId = currentTenant?.id || user?.tenant_id;
  const basePath = tenantId ? `/tenant/${tenantId}/plugins` : '/tenant/plugins';
  const projectQuery = projectId ? `?projectId=${encodeURIComponent(projectId)}` : '';

  return <Navigate to={`${basePath}${projectQuery}`} replace />;
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
  const user = useAuthStore((state) => state.user);
  const projects = useProjectStore((state) => state.projects);
  const getProject = useProjectStore((state) => state.getProject);
  const [resolvedPath, setResolvedPath] = useState<string | null>(null);
  const normalizedQuery = query || '';
  const fallbackPath = `/tenant/projects${normalizedQuery}`;

  useEffect(() => {
    let cancelled = false;

    if (!projectId) {
      return () => {
        cancelled = true;
      };
    }

    const trustedTenantId =
      currentTenant?.id && projects.some((project) => project.id === projectId)
        ? currentTenant.id
        : undefined;
    const candidateTenantIds = [trustedTenantId, currentTenant?.id, user?.tenant_id].filter(
      (tenantId, index, values): tenantId is string =>
        Boolean(tenantId) && values.indexOf(tenantId) === index
    );

    const resolvePath = async () => {
      if (trustedTenantId) {
        return buildCanonicalProjectRedirectPath({
          tenantId: trustedTenantId,
          projectId,
          rest,
          query: normalizedQuery,
        });
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

      return fallbackPath;
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
    getProject,
    normalizedQuery,
    projectId,
    projects,
    rest,
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

export const LegacyProjectRedirect: React.FC = () => {
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

export const LegacyTenantWorkspaceRedirect: React.FC = () => {
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

export const LegacyTenantConversationRedirect: React.FC = () => {
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

// Redirect after successful login: honour ?redirect= param when it is a
// same-origin path. Falls back to '/'. Exists so that deep links such as
// /device?user_code=X can be preserved through the login round-trip.
const LoginRedirect = () => {
  const [params] = useSearchParams();
  const raw = params.get('redirect');
  const safe = raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/';
  return <Navigate to={safe} replace />;
};

// Redirect unauthenticated users to /login while preserving the current
// location (path + search) as ?redirect=, so that after sign-in they are
// returned to where they originally wanted to go. Paired with LoginRedirect.
const RedirectToLogin = () => {
  const location = useLocation();
  const target = `${location.pathname}${location.search}`;
  const safe = target.startsWith('/') && !target.startsWith('//') ? target : '/';
  const loginHref =
    safe === '/' || safe === '/login' ? '/login' : `/login?redirect=${encodeURIComponent(safe)}`;
  return <Navigate to={loginHref} replace />;
};

function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const mustChangePassword = isAuthenticated && user?.must_change_password === true;

  return (
    <ErrorBoundary>
      <ThemeProvider>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/login" element={!isAuthenticated ? <Login /> : <LoginRedirect />} />
            <Route
              path="/login/callback/:provider"
              element={
                <Suspense fallback={<PageLoader />}>
                  <OAuthCallback />
                </Suspense>
              }
            />
            <Route
              path="/invite/:token"
              element={
                <Suspense fallback={<PageLoader />}>
                  <InviteAccept />
                </Suspense>
              }
            />
            <Route
              path="/device"
              element={
                <Suspense fallback={<PageLoader />}>
                  <DeviceApprove />
                </Suspense>
              }
            />

            {/* Force Change Password */}
            <Route
              path="/force-change-password"
              element={
                isAuthenticated ? (
                  <Suspense fallback={<PageLoader />}>
                    <ForceChangePassword />
                  </Suspense>
                ) : (
                  <Navigate to="/login" replace />
                )
              }
            />

            {/* Protected Routes */}
            {/* Redirect root to tenant overview if authenticated */}
            <Route
              path="/"
              element={
                mustChangePassword ? (
                  <Navigate to="/force-change-password" replace />
                ) : isAuthenticated ? (
                  <Navigate to="/tenant" replace />
                ) : (
                  <Navigate to="/login" replace />
                )
              }
            />

            <Route
              path="/tenants/new"
              element={
                isAuthenticated ? (
                  <Suspense fallback={<PageLoader />}>
                    <NewTenant />
                  </Suspense>
                ) : (
                  <RedirectToLogin />
                )
              }
            />

            {/* Tenant Console */}
            <Route
              path="/tenant"
              element={
                mustChangePassword ? (
                  <Navigate to="/force-change-password" replace />
                ) : isAuthenticated ? (
                  <OrgSetupGuard>
                    <TenantLayout />
                  </OrgSetupGuard>
                ) : (
                  <RedirectToLogin />
                )
              }
            >
              <Route
                index
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentWorkspace />
                  </Suspense>
                }
              />
              <Route
                path=":conversation"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentWorkspace />
                  </Suspense>
                }
              />
              <Route
                path="overview"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TenantOverview />
                  </Suspense>
                }
              />

              {/* Generic routes (use currentTenant from store) */}
              <Route
                path="projects"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <ProjectList />
                  </Suspense>
                }
              />
              <Route
                path="projects/new"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <NewProject />
                  </Suspense>
                }
              />
              <Route
                path="users"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <UserList />
                  </Suspense>
                }
              />
              <Route
                path="providers"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <ProviderList />
                  </Suspense>
                }
              />
              <Route
                path="profile"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <UserProfile />
                  </Suspense>
                }
              />
              <Route
                path="analytics"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Analytics />
                  </Suspense>
                }
              />
              <Route
                path="events"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Events />
                  </Suspense>
                }
              />
              <Route
                path="webhooks"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Webhooks />
                  </Suspense>
                }
              />
              <Route
                path="billing"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Billing />
                  </Suspense>
                }
              />
              <Route
                path="settings"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TenantSettings />
                  </Suspense>
                }
              />
              <Route
                path="tasks"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TaskDashboard />
                  </Suspense>
                }
              />
              <Route
                path="workspaces"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <WorkspaceList />
                  </Suspense>
                }
              />
              <Route
                path="workspaces/new"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <WorkspaceCreate />
                  </Suspense>
                }
              />
              <Route
                path="agents"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentDashboard />
                  </Suspense>
                }
              />
              <Route
                path="agent-workspace"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentWorkspace />
                  </Suspense>
                }
              />
              <Route
                path="agent-workspace/:conversation"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentWorkspace />
                  </Suspense>
                }
              />
              <Route
                path="subagents"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <SubAgentList />
                  </Suspense>
                }
              />
              <Route
                path="agent-definitions"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentDefinitions />
                  </Suspense>
                }
              />
              <Route
                path="agent-bindings"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentBindings />
                  </Suspense>
                }
              />
              <Route
                path="skills"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <SkillList />
                  </Suspense>
                }
              />
              <Route
                path="curated-skills"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <CuratedSkills />
                  </Suspense>
                }
              />
              <Route
                path="templates"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TemplateMarketplace />
                  </Suspense>
                }
              />
              <Route
                path="plugins"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <PluginHub />
                  </Suspense>
                }
              />
              <Route
                path="mcp-servers"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <McpServerList />
                  </Suspense>
                }
              />
              <Route
                path="instances"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <InstanceList />
                  </Suspense>
                }
              />
              <Route
                path="instances/create"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <CreateInstance />
                  </Suspense>
                }
              />
              <Route
                path="instances/:instanceId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <InstanceLayout />
                  </Suspense>
                }
              >
                <Route
                  index
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceOverview />
                    </Suspense>
                  }
                />
                <Route
                  path="files"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceFiles />
                    </Suspense>
                  }
                />
                <Route
                  path="channels"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceChannels />
                    </Suspense>
                  }
                />
                <Route
                  path="members"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceMembers />
                    </Suspense>
                  }
                />
                <Route
                  path="genes"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceGenes />
                    </Suspense>
                  }
                />
                <Route
                  path="settings"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceSettings />
                    </Suspense>
                  }
                />
              </Route>
              <Route
                path="instances/:instanceId/deploy"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <DeployProgress />
                  </Suspense>
                }
              />
              <Route
                path="audit-logs"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AuditLogs />
                  </Suspense>
                }
              />
              <Route
                path="trust-policies"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TrustPolicies />
                  </Suspense>
                }
              />
              <Route
                path="decision-records"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <DecisionRecords />
                  </Suspense>
                }
              />
              <Route path="org-settings" element={<OrgSettingsLayout />}>
                <Route
                  index
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgInfo />
                    </Suspense>
                  }
                />
                <Route
                  path="info"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgInfo />
                    </Suspense>
                  }
                />
                <Route
                  path="members"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgMembers />
                    </Suspense>
                  }
                />
                <Route
                  path="clusters"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgClusters />
                    </Suspense>
                  }
                />
                <Route
                  path="audit"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgAudit />
                    </Suspense>
                  }
                />
                <Route
                  path="registry"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgRegistry />
                    </Suspense>
                  }
                />
                <Route
                  path="smtp"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgSmtp />
                    </Suspense>
                  }
                />
                <Route
                  path="genes"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgGenes />
                    </Suspense>
                  }
                />
              </Route>
              <Route
                path="deploy"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <DeployProgress />
                  </Suspense>
                }
              />
              <Route
                path="deploy/:deployId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <DeployProgress />
                  </Suspense>
                }
              />
              <Route
                path="clusters"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <ClusterList />
                  </Suspense>
                }
              />
              <Route
                path="clusters/:clusterId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <ClusterDetail />
                  </Suspense>
                }
              />
              <Route
                path="genes"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <GeneMarket />
                  </Suspense>
                }
              />
              <Route
                path="genes/:geneId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <GeneDetail />
                  </Suspense>
                }
              />
              <Route
                path="instance-templates"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <InstanceTemplateList />
                  </Suspense>
                }
              />
              <Route
                path="instance-templates/:templateId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TemplateDetail />
                  </Suspense>
                }
              />
              <Route
                path="instances/:instanceId/evolution"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <EvolutionLog />
                  </Suspense>
                }
              />
              <Route
                path="genes/genomes/:genomeId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <GenomeDetail />
                  </Suspense>
                }
              />

              {/* Project routes (generic, no tenantId in URL) - compatibility redirect only */}
              <Route path="project/:projectId/*" element={<GenericTenantProjectRedirect />} />

              {/* Tenant specific routes */}
              <Route
                path=":tenantId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <LegacyTenantWorkspaceRedirect />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/:conversation"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <LegacyTenantConversationRedirect />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/overview"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TenantOverview />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/tasks"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TaskDashboard />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/workspaces"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <WorkspaceList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/workspaces/new"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <WorkspaceCreate />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/agents"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentDashboard />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/agent-workspace/:conversation?"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentWorkspace />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/projects"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <ProjectList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/projects/new"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <NewProject />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/projects/:projectId/edit"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <EditProject />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/users"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <UserList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/providers"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <ProviderList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/analytics"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Analytics />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/events"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Events />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/webhooks"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Webhooks />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/billing"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <Billing />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/settings"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TenantSettings />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/org-settings"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <OrgSettingsLayout />
                  </Suspense>
                }
              >
                <Route index element={<Navigate to="info" replace />} />
                <Route
                  path="info"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgInfo />
                    </Suspense>
                  }
                />
                <Route
                  path="members"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgMembers />
                    </Suspense>
                  }
                />
                <Route
                  path="clusters"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgClusters />
                    </Suspense>
                  }
                />
                <Route
                  path="audit"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgAudit />
                    </Suspense>
                  }
                />
                <Route
                  path="registry"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgRegistry />
                    </Suspense>
                  }
                />
                <Route
                  path="smtp"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgSmtp />
                    </Suspense>
                  }
                />
                <Route
                  path="genes"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <OrgGenes />
                    </Suspense>
                  }
                />
              </Route>
              <Route
                path=":tenantId/patterns"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <WorkflowPatterns />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/subagents"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <SubAgentList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/agent-definitions"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentDefinitions />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/agent-bindings"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AgentBindings />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/skills"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <SkillList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/templates"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TemplateMarketplace />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/plugins"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <PluginHub />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/mcp-servers"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <McpServerList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/pool"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <PoolDashboard />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/skill-review"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AdminSkillReview />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/instances"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <InstanceList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/instances/create"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <CreateInstance />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/instances/:instanceId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <InstanceLayout />
                  </Suspense>
                }
              >
                <Route
                  index
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceOverview />
                    </Suspense>
                  }
                />
                <Route
                  path="files"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceFiles />
                    </Suspense>
                  }
                />
                <Route
                  path="channels"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceChannels />
                    </Suspense>
                  }
                />
                <Route
                  path="members"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceMembers />
                    </Suspense>
                  }
                />
                <Route
                  path="genes"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceGenes />
                    </Suspense>
                  }
                />
                <Route
                  path="settings"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <InstanceSettings />
                    </Suspense>
                  }
                />
              </Route>
              <Route
                path=":tenantId/instances/:instanceId/deploy"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <DeployProgress />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/audit-logs"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <AuditLogs />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/trust-policies"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TrustPolicies />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/decision-records"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <DecisionRecords />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/deploy"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <DeployProgress />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/deploy/:deployId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <DeployProgress />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/clusters"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <ClusterList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/clusters/:clusterId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <ClusterDetail />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/genes"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <GeneMarket />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/genes/:geneId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <GeneDetail />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/instance-templates"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <InstanceTemplateList />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/instance-templates/:templateId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <TemplateDetail />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/instances/:instanceId/evolution"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <EvolutionLog />
                  </Suspense>
                }
              />
              <Route
                path=":tenantId/genes/genomes/:genomeId"
                element={
                  <Suspense fallback={<PageLoader />}>
                    <GenomeDetail />
                  </Suspense>
                }
              />

              {/* Project routes (tenantId-prefixed) */}
              <Route path=":tenantId/project/:projectId">
                <Route
                  index
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <ProjectOverview />
                    </Suspense>
                  }
                />
                <Route
                  path="memories"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <MemoryList />
                    </Suspense>
                  }
                />
                <Route
                  path="memories/new"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <NewMemory />
                    </Suspense>
                  }
                />
                <Route
                  path="memory/:memoryId"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <MemoryDetail />
                    </Suspense>
                  }
                />
                <Route
                  path="graph"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <MemoryGraph />
                    </Suspense>
                  }
                />
                <Route
                  path="entities"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <EntitiesList />
                    </Suspense>
                  }
                />
                <Route
                  path="communities"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <CommunitiesList />
                    </Suspense>
                  }
                />
                <Route
                  path="advanced-search"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <EnhancedSearch />
                    </Suspense>
                  }
                />
                <Route path="search" element={<Navigate to="advanced-search" replace />} />
                <Route
                  path="maintenance"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <Maintenance />
                    </Suspense>
                  }
                />
                <Route
                  path="cron-jobs"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <CronJobs />
                    </Suspense>
                  }
                />
                <Route path="schema" element={<SchemaLayout />}>
                  <Route
                    index
                    element={
                      <Suspense fallback={<PageLoader />}>
                        <SchemaOverview />
                      </Suspense>
                    }
                  />
                  <Route
                    path="entities"
                    element={
                      <Suspense fallback={<PageLoader />}>
                        <EntityTypeList />
                      </Suspense>
                    }
                  />
                  <Route
                    path="edges"
                    element={
                      <Suspense fallback={<PageLoader />}>
                        <EdgeTypeList />
                      </Suspense>
                    }
                  />
                  <Route
                    path="mapping"
                    element={
                      <Suspense fallback={<PageLoader />}>
                        <EdgeMapList />
                      </Suspense>
                    }
                  />
                </Route>
                <Route path="channels" element={<ProjectChannelsRedirect />} />
                <Route
                  path="team"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <Team />
                    </Suspense>
                  }
                />
                <Route
                  path="settings"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <ProjectSettings />
                    </Suspense>
                  }
                />
                <Route
                  path="support"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <Support />
                    </Suspense>
                  }
                />
                <Route
                  path="blackboard"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <Blackboard />
                    </Suspense>
                  }
                />
                <Route
                  path="workspaces"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <WorkspaceList />
                    </Suspense>
                  }
                />
                <Route
                  path="workspaces/new"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <WorkspaceCreate />
                    </Suspense>
                  }
                />
                <Route
                  path="workspaces/:workspaceId"
                  element={
                    <Suspense fallback={<PageLoader />}>
                      <WorkspaceBlackboardRedirect />
                    </Suspense>
                  }
                />
              </Route>
            </Route>

            {/* Legacy /project/:projectId redirect to tenant-scoped route */}
            <Route
              path="/project/:projectId/*"
              element={isAuthenticated ? <LegacyProjectRedirect /> : <RedirectToLogin />}
            />

            {/* Fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
