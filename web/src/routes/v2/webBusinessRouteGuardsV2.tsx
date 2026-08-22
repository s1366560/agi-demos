import { Suspense } from 'react';

import { Navigate } from 'react-router-dom';

import { OrgSetupGuard } from '../../components/common/OrgSetupGuard';
import { TenantLayout } from '../../layouts/TenantLayout';
import { useAuthStore } from '../../stores/auth';

import { RedirectToLogin } from './webCoreRouteRedirectsV2';
import { NewTenant } from './webDefaultRouteComponentsV2';
import { WebRoutePageLoaderV2 as PageLoader } from './WebRoutePageLoaderV2';
import { LegacyProjectRedirect, LegacyTenantAuditLogsRedirect } from './webRouteRedirectsV2';

export function NewTenantRouteV2() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? (
    <Suspense fallback={<PageLoader />}>
      <NewTenant />
    </Suspense>
  ) : (
    <RedirectToLogin />
  );
}

export function LegacyAuditLogsRouteV2() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const mustChangePassword = useAuthStore((state) => state.user?.must_change_password === true);
  if (mustChangePassword) return <Navigate to="/force-change-password" replace />;
  return isAuthenticated ? <LegacyTenantAuditLogsRedirect /> : <RedirectToLogin />;
}

export function TenantConsoleShellV2() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const mustChangePassword = useAuthStore((state) => state.user?.must_change_password === true);
  if (mustChangePassword) return <Navigate to="/force-change-password" replace />;
  return isAuthenticated ? (
    <OrgSetupGuard>
      <TenantLayout />
    </OrgSetupGuard>
  ) : (
    <RedirectToLogin />
  );
}

export function LegacyProjectRouteV2() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? <LegacyProjectRedirect /> : <RedirectToLogin />;
}
