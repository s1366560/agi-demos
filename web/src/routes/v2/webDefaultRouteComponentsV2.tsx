import { lazy } from 'react';

import { TenantPackageRouteFallback } from './webRouteRedirectsV2';

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
export const McpServerList = SignedBusinessPage;

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

export const Team = SignedBusinessPage;
export const ProjectSettings = SignedBusinessPage;

// Business pages


/** Business routes render through signed packages, not the host document. */
function SignedBusinessPage() {
  return <TenantPackageRouteFallback />;
}
export const AcpDashboard = SignedBusinessPage;
export const AgentBindings = SignedBusinessPage;
export const AgentDashboard = SignedBusinessPage;
export const AgentDefinitionDetail = SignedBusinessPage;
export const AgentDefinitions = SignedBusinessPage;
export const AgentWorkspace = SignedBusinessPage;
export const Analytics = SignedBusinessPage;
export const BackendStores = SignedBusinessPage;
export const ClusterDetail = SignedBusinessPage;
export const CommunitiesList = SignedBusinessPage;
export const CreateInstance = SignedBusinessPage;
export const DeadLetterQueue = SignedBusinessPage;
export const DeployProgress = SignedBusinessPage;
export const EdgeMapList = SignedBusinessPage;
export const EdgeTypeList = SignedBusinessPage;
export const EnhancedSearch = SignedBusinessPage;
export const EntityTypeList = SignedBusinessPage;
export const Events = SignedBusinessPage;
export const EvolutionLog = SignedBusinessPage;
export const GeneDetail = SignedBusinessPage;
export const GeneMarket = SignedBusinessPage;
export const GenomeDetail = SignedBusinessPage;
export const InstanceChannels = SignedBusinessPage;
export const InstanceFiles = SignedBusinessPage;
export const InstanceGenes = SignedBusinessPage;
export const InstanceLayout = SignedBusinessPage;
export const InstanceList = SignedBusinessPage;
export const InstanceMembers = SignedBusinessPage;
export const InstanceOverview = SignedBusinessPage;
export const InstanceSettings = SignedBusinessPage;
export const InstanceTemplateList = SignedBusinessPage;
export const Maintenance = SignedBusinessPage;
export const MemoryGraph = SignedBusinessPage;
export const OrgClusters = SignedBusinessPage;
export const OrgGenes = SignedBusinessPage;
export const PoolDashboard = SignedBusinessPage;
export const ProjectAgentDashboard = SignedBusinessPage;
export const ProjectAgentLogs = SignedBusinessPage;
export const ProjectAgentPatterns = SignedBusinessPage;
export const ProjectOverview = SignedBusinessPage;
export const ProviderList = SignedBusinessPage;
export const SchemaOverview = SignedBusinessPage;
export const SkillDetail = SignedBusinessPage;
export const SkillEvolution = SignedBusinessPage;
export const SkillList = SignedBusinessPage;
export const SubAgentList = SignedBusinessPage;
export const Support = SignedBusinessPage;
export const TaskDashboard = SignedBusinessPage;
export const TemplateDetail = SignedBusinessPage;
export const TemplateMarketplace = SignedBusinessPage;
export const TenantOverview = SignedBusinessPage;
export const UnifiedRuntimes = SignedBusinessPage;
export const Webhooks = SignedBusinessPage;
export const WorkspaceList = SignedBusinessPage;
