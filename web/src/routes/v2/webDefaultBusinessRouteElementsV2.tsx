import type { ReactNode } from 'react';

import { Route } from 'react-router-dom';

import {
  LegacyAuditLogsRouteV2,
  LegacyProjectRouteV2,
  NewTenantRouteV2,
  TenantConsoleShellV2,
} from './webBusinessRouteGuardsV2';
import { createProjectRouteElementsV2 } from './webProjectRouteElementsV2';
import { GenericTenantProjectRedirect } from './webRouteRedirectsV2';
import { createTenantGenericRouteElementsV2 } from './webTenantGenericRouteElementsV2';
import { createTenantScopedRouteElementsV2 } from './webTenantScopedRouteElementsV2';

export function createDefaultBusinessRouteElementsV2(): ReactNode {
  return (
    <>
      <Route path="/tenants/new" element={<NewTenantRouteV2 />} />
      <Route path="/audit-logs" element={<LegacyAuditLogsRouteV2 />} />
      <Route path="/tenant" element={<TenantConsoleShellV2 />}>
        {createTenantGenericRouteElementsV2()}
        <Route path="project/:projectId/*" element={<GenericTenantProjectRedirect />} />
        {createTenantScopedRouteElementsV2()}
        {createProjectRouteElementsV2()}
      </Route>
      <Route path="/project/:projectId/*" element={<LegacyProjectRouteV2 />} />
    </>
  );
}
