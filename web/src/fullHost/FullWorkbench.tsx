import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { TenantLayoutView } from '../layouts/TenantLayoutView';
import { TenantPackageBookmark } from '../projectPackages/TenantPackageBookmark';
import { ProjectBusinessRoute } from '../projectPackages/ProjectBusinessRoute';
import { LoginRedirect, RedirectToLogin } from '../routes/v2/webCoreRouteRedirectsV2';
import { useAuthStore } from '../stores/auth';
import { Login } from '../pages/Login';
import { PluginHubView } from '../pages/tenant/PluginHubView';
import { WebRoutePageLoaderV2 } from '../routes/v2/WebRoutePageLoaderV2';
import { FullNavigation, useFullNavigation } from './navigation';
import { SignedSidebarProvider } from './sidebarData';
import { FullHeader, FullPalette, FullSidebar } from './WorkbenchControls';
import { tenantAdministrationRoutes } from './tenantAdministration';
import { CompatibilityPage } from './compatibility';

const Projects = lazy(() =>
  import('../pages/tenant/ProjectList').then((m) => ({ default: m.ProjectList }))
);
const NewProject = lazy(() =>
  import('../pages/tenant/NewProject').then((m) => ({ default: m.NewProject }))
);
const EditProject = lazy(() =>
  import('../pages/tenant/EditProject').then((m) => ({ default: m.EditProject }))
);
const Settings = lazy(() =>
  import('../pages/tenant/TenantSettings').then((m) => ({ default: m.TenantSettings }))
);
const Profile = lazy(() =>
  import('../pages/UserProfile').then((m) => ({ default: m.UserProfile }))
);
const Password = lazy(() =>
  import('../pages/ForceChangePassword').then((m) => ({ default: m.ForceChangePassword }))
);
const OAuth = lazy(() =>
  import('../pages/OAuthCallback').then((m) => ({ default: m.OAuthCallback }))
);
const Device = lazy(() =>
  import('../pages/DeviceApprove').then((m) => ({ default: m.DeviceApprove }))
);
const Invite = lazy(() =>
  import('../pages/InviteAccept').then((m) => ({ default: m.InviteAccept }))
);

function Layout() {
  const scope = useFullNavigation();
  return (
    <SignedSidebarProvider>
      <TenantLayoutView
        Sidebar={FullSidebar}
        Header={FullHeader}
        Palette={FullPalette}
        scope={scope}
        landing="projects"
      />
    </SignedSidebarProvider>
  );
}
function PackageHub() {
  const { invalidate } = useFullNavigation();
  return <PluginHubView integrationSettings={<CompatibilityPage />} onChanged={invalidate} />;
}
function BusinessPage() {
  const { tenant, project } = useFullNavigation();
  const market =
    '/tenant/' +
    encodeURIComponent(tenant) +
    '/plugins' +
    (project ? '?projectId=' + encodeURIComponent(project) : '');
  return (
    <ProjectBusinessRoute insideWorkbench matchesFullRoute={() => false}>
      <CompatibilityPage market={market} />
    </ProjectBusinessRoute>
  );
}
function TenantEntry() {
  const { tenantId } = useParams();
  return (
    <Navigate
      replace
      to={tenantId ? '/tenant/' + encodeURIComponent(tenantId) + '/projects' : '/tenant'}
    />
  );
}

export function FullWorkbench() {
  const authenticated = useAuthStore((s) => s.isAuthenticated);
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password);
  const { pathname } = useLocation();
  const { t } = useTranslation();
  if (
    !authenticated &&
    pathname !== '/login' &&
    !pathname.startsWith('/login/callback/') &&
    !pathname.startsWith('/invite/')
  )
    return <RedirectToLogin />;
  if (authenticated && mustChangePassword && pathname !== '/force-change-password')
    return <Navigate replace to="/force-change-password" />;
  return (
    <Suspense fallback={<WebRoutePageLoaderV2 />}>
      <FullNavigation>
        <Routes>
          <Route path="/login" element={authenticated ? <LoginRedirect /> : <Login />} />
          <Route path="/login/callback/:provider" element={<OAuth />} />
          <Route path="/invite/:token" element={<Invite />} />
          <Route path="/device" element={<Device />} />
          <Route path="/force-change-password" element={<Password />} />
          <Route path="/" element={<Navigate to="/tenant" replace />} />
          {[
            'clusters/*',
            'deploy/*',
            'instances/*',
            'instance-templates/*',
            'pool',
            'events',
            'webhooks',
            'workspaces',
            'workspaces/new',
            'agent-workspace/*',
            'patterns',
            'billing',
            'plugins',
            'projects',
            'settings',
            'profile',
            'users',
            'audit-logs',
            'org-settings/*',
          ].map((segment) => (
            <Route key={segment} path={'/tenant/' + segment} element={<TenantPackageBookmark />} />
          ))}
          <Route element={<Layout />}>
            {tenantAdministrationRoutes()}
            <Route path="/tenant" element={<p role="status">{t('common.loading')}</p>} />
            <Route path="/tenant/:tenantId" element={<TenantEntry />} />
            <Route
              path="/tenant/:tenantId/plugins"
              element={<PackageHub />}
            />
            <Route path="/tenant/:tenantId/projects" element={<Projects />} />
            <Route path="/tenant/:tenantId/projects/new" element={<NewProject />} />
            <Route path="/tenant/:tenantId/projects/:projectId/edit" element={<EditProject />} />
            <Route path="/tenant/:tenantId/settings" element={<Settings />} />
            <Route path="/tenant/:tenantId/profile" element={<Profile />} />
            <Route path="/tenant/:tenantId/project/:projectId/*" element={<BusinessPage />} />
            <Route path="/tenant/:tenantId/*" element={<BusinessPage />} />
            <Route path="*" element={<BusinessPage />} />
          </Route>
        </Routes>
      </FullNavigation>
    </Suspense>
  );
}
