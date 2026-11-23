import { lazy } from 'react';

export const UserProfile = lazy(() =>
  import('../../pages/UserProfile').then((m) => ({ default: m.UserProfile }))
);
// Tenant pages

const projectListModule = import('../../pages/tenant/ProjectList');
export const ProjectList = lazy(() => projectListModule.then((m) => ({ default: m.ProjectList })));

export const UserList = lazy(() =>
  import('../../pages/tenant/UserList').then((m) => ({ default: m.UserList }))
);

export const NewProject = lazy(() =>
  import('../../pages/tenant/NewProject').then((m) => ({ default: m.NewProject }))
);
export const EditProject = lazy(() =>
  import('../../pages/tenant/EditProject').then((m) => ({ default: m.EditProject }))
);
export const NewTenant = lazy(() =>
  import('../../pages/tenant/NewTenant').then((m) => ({ default: m.NewTenant }))
);
export const TenantSettings = lazy(() =>
  import('../../pages/tenant/TenantSettings').then((m) => ({
    default: m.TenantSettings,
  }))
);
// Organization Settings
export const OrgSettingsLayout = lazy(() =>
  import('../../pages/tenant/org-settings/OrgSettingsLayout').then((m) => ({
    default: m.OrgSettingsLayout,
  }))
);
export const OrgInfo = lazy(() =>
  import('../../pages/tenant/org-settings/OrgInfo').then((m) => ({ default: m.OrgInfo }))
);
export const OrgMembers = lazy(() =>
  import('../../pages/tenant/org-settings/OrgMembers').then((m) => ({ default: m.OrgMembers }))
);

export const OrgAudit = lazy(() =>
  import('../../pages/tenant/org-settings/OrgAudit').then((m) => ({ default: m.OrgAudit }))
);
export const OrgRegistry = lazy(() =>
  import('../../pages/tenant/org-settings/OrgRegistry').then((m) => ({ default: m.OrgRegistry }))
);
export const OrgSmtp = lazy(() =>
  import('../../pages/tenant/org-settings/OrgSmtp').then((m) => ({ default: m.OrgSmtp }))
);

export const PluginHub = lazy(() =>
  import('../../pages/tenant/PluginHub').then((m) => ({
    default: m.PluginHub,
  }))
);
export const PluginDetail = lazy(() =>
  import('../../pages/tenant/PluginDetail').then((m) => ({
    default: m.PluginDetail,
  }))
);
export const McpServerList = lazy(() =>
  import('../../components/mcp/McpServerListV2').then((m) => ({
    default: m.McpServerListV2,
  }))
);

export const AuditLogs = lazy(() =>
  import('../../pages/tenant/AuditLogs').then((m) => ({ default: m.AuditLogs }))
);
export const TrustPolicies = lazy(() =>
  import('../../pages/tenant/TrustPolicies').then((m) => ({ default: m.TrustPolicies }))
);
export const DecisionRecords = lazy(() =>
  import('../../pages/tenant/DecisionRecords').then((m) => ({ default: m.DecisionRecords }))
);

// Project pages

export const Team = lazy(() =>
  import('../../pages/project/Team').then((m) => ({ default: m.Team }))
);
export const ProjectSettings = lazy(() =>
  import('../../pages/project/Settings').then((m) => ({
    default: m.ProjectSettings,
  }))
);

// Business pages

export * from '@business/agent/ui/web/routes';
export * from '@business/automation/ui/web/routes';
export * from '@business/billing/ui/web/routes';
export * from '@business/environments/ui/web/routes';
export * from '@business/knowledge/ui/web/routes';
export * from '@business/workspace/ui/web/routes';
