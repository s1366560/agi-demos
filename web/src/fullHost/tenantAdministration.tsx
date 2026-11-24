import { lazy } from 'react';
import { Navigate, Route } from 'react-router-dom';

import { CompatibilityPage } from './compatibility';

const Users = lazy(() =>
  import('../pages/tenant/UserList').then(({ UserList }) => ({ default: UserList }))
);
const Audit = lazy(() =>
  import('../pages/tenant/AuditLogs').then(({ AuditLogs }) => ({ default: AuditLogs }))
);
const Organization = lazy(() => import('../pages/tenant/org-settings/OrgSettingsLayout'));
const Info = lazy(() => import('../pages/tenant/org-settings/OrgInfo'));
const Members = lazy(() => import('../pages/tenant/org-settings/OrgMembers'));
const OrganizationAudit = lazy(() => import('../pages/tenant/org-settings/OrgAudit'));
const Smtp = lazy(() => import('../pages/tenant/org-settings/OrgSmtp'));
const Registry = lazy(() => import('../pages/tenant/org-settings/OrgRegistry'));

export function tenantAdministrationRoutes() {
  return (
    <Route path="/tenant/:tenantId">
      <Route path="users" element={<Users />} />
      <Route path="audit-logs" element={<Audit />} />
      <Route path="org-settings" element={<Organization />}>
        <Route index element={<Navigate to="info" replace />} />
        <Route path="info" element={<Info />} />
        <Route path="members" element={<Members />} />
        <Route path="audit" element={<OrganizationAudit />} />
        <Route path="smtp" element={<Smtp />} />
        <Route path="registry" element={<Registry />} />
        <Route path="*" element={<CompatibilityPage />} />
      </Route>
    </Route>
  );
}
