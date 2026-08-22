import { lazy, type ComponentType } from 'react';

export const UserProfile = lazy(() =>
  import('../../pages/UserProfile').then((m) => ({ default: m.UserProfile }))
);
// Tenant pages
export const TenantOverview = lazy(() =>
  import('../../pages/tenant/TenantOverview').then((m) => ({
    default: m.TenantOverview,
  }))
);
export const ProjectList = lazy(() =>
  import('../../pages/tenant/ProjectList').then((m) => ({ default: m.ProjectList }))
);
export const BackendStores = lazy(() =>
  import('../../pages/tenant/BackendStores').then((m) => ({ default: m.BackendStores }))
);
export const UserList = lazy(() =>
  import('../../pages/tenant/UserList').then((m) => ({ default: m.UserList }))
);
export const ProviderList = lazy(() =>
  import('../../pages/tenant/ProviderList').then((m) => ({
    default: m.ProviderList,
  }))
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
export const OrgClusters = lazy(() =>
  import('../../pages/tenant/org-settings/OrgClusters').then((m) => ({ default: m.OrgClusters }))
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
export const OrgGenes = lazy(() =>
  import('../../pages/tenant/org-settings/OrgGenes').then((m) => ({ default: m.OrgGenes }))
);
export const TaskDashboard = lazy(() =>
  import('../../pages/tenant/TaskDashboard').then((m) => ({
    default: m.TaskDashboard,
  }))
);
export const AgentDashboard = lazy(() =>
  import('../../pages/tenant/AgentDashboard').then((m) => ({
    default: m.AgentDashboard,
  }))
);
export const ProjectAgentDashboard = lazy(
  () => import('../../pages/project/ProjectAgentDashboard')
);
export const ProjectAgentLogs = lazy(() => import('../../pages/project/ProjectAgentLogs'));
export const ProjectAgentPatterns = lazy(() => import('../../pages/project/ProjectAgentPatterns'));
export const WorkflowPatterns = lazy(() => import('../../pages/tenant/WorkflowPatterns'));
export const Analytics = lazy(() =>
  import('../../pages/tenant/Analytics').then((m) => ({ default: m.Analytics }))
);
export const Billing = lazy(() =>
  import('../../pages/tenant/Billing').then((m) => ({ default: m.Billing }))
);
export const Events = lazy(() =>
  import('../../pages/tenant/Events').then((m) => ({ default: m.Events }))
);
export const Webhooks = lazy(() =>
  import('../../pages/tenant/Webhooks').then((m) => ({ default: m.Webhooks }))
);
export const SubAgentList = lazy(() =>
  import('../../pages/tenant/SubAgentList').then((m) => ({
    default: m.SubAgentList,
  }))
);
export const SkillList = lazy(() =>
  import('../../pages/tenant/SkillList').then((m) => ({ default: m.SkillList }))
);
export const SkillEvolution = lazy(() =>
  import('../../pages/tenant/SkillEvolution').then((m) => ({ default: m.SkillEvolution }))
);
export const SkillDetail = lazy(() =>
  import('../../pages/tenant/SkillDetail').then((m) => ({ default: m.SkillDetail }))
);
export const TemplateMarketplace = lazy(() =>
  import('../../pages/tenant/TemplateMarketplace').then((m) => ({
    default: m.TemplateMarketplace,
  }))
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
export const AcpDashboard = lazy(() =>
  import('../../pages/tenant/AcpDashboard').then((m) => ({
    default: m.AcpDashboard,
  }))
);
export const UnifiedRuntimes = lazy(() =>
  import('../../pages/tenant/UnifiedRuntimes').then((m) => ({ default: m.UnifiedRuntimes }))
);
export const AgentDefinitions = lazy(() =>
  import('../../pages/tenant/AgentDefinitions').then((m) => ({ default: m.AgentDefinitions }))
);
export const AgentDefinitionDetail = lazy(() =>
  import('../../pages/tenant/AgentDefinitionDetail').then((m) => ({
    default: m.AgentDefinitionDetail,
  }))
);
export const AgentBindings = lazy(() =>
  import('../../pages/tenant/AgentBindings').then((m) => ({ default: m.AgentBindings }))
);
export const AgentWorkspace = lazy(() =>
  import('../../pages/tenant/AgentWorkspace').then((m) => ({
    default: m.AgentWorkspace,
  }))
);
export const WorkspaceList = lazy(() =>
  import('../../pages/tenant/WorkspaceList').then((m) => ({ default: m.WorkspaceList }))
);
export const WorkspaceCreate = lazy(() =>
  import('../../pages/tenant/WorkspaceCreate').then((m) => ({ default: m.WorkspaceCreate }))
);
export const WorkspaceBlackboardRedirect = lazy(() =>
  import('../../pages/project/WorkspaceBlackboardRedirect').then((m) => ({
    default: m.WorkspaceBlackboardRedirect,
  }))
);
export const InstanceList = lazy(() =>
  import('../../pages/tenant/InstanceList').then((m) => ({ default: m.InstanceList }))
);
export const InstanceLayout = lazy(() =>
  import('../../pages/tenant/InstanceLayout').then((m) => ({ default: m.InstanceLayout }))
);
export const InstanceOverview = lazy(() =>
  import('../../pages/tenant/InstanceOverview').then((m) => ({ default: m.InstanceOverview }))
);
export const CreateInstance = lazy(() =>
  import('../../pages/tenant/CreateInstance').then((m) => ({ default: m.CreateInstance }))
);
export const DeployProgress = lazy(() =>
  import('../../pages/tenant/DeployProgress').then((m) => ({ default: m.DeployProgress }))
);
export const ClusterList = lazy(() =>
  import('../../pages/tenant/ClusterList').then((m) => ({ default: m.ClusterList }))
);
export const ClusterDetail = lazy(() =>
  import('../../pages/tenant/ClusterDetail').then((m) => ({ default: m.ClusterDetail }))
);
export const GeneMarket = lazy(() =>
  import('../../pages/tenant/GeneMarket').then((m) => ({ default: m.GeneMarket }))
);
export const GeneDetail = lazy(() =>
  import('../../pages/tenant/GeneDetail').then((m) => ({ default: m.GeneDetail }))
);
export const InstanceTemplateList = lazy(() =>
  import('../../pages/tenant/InstanceTemplateList').then((m) => ({
    default: m.InstanceTemplateList,
  }))
);
export const InstanceMembers = lazy(() =>
  import('../../pages/tenant/InstanceMembers').then((m) => ({ default: m.InstanceMembers }))
);
export const InstanceSettings = lazy(() =>
  import('../../pages/tenant/InstanceSettings').then((m) => ({ default: m.InstanceSettings }))
);
export const InstanceGenes = lazy(() =>
  import('../../pages/tenant/InstanceGenes').then((m) => ({ default: m.InstanceGenes }))
);
export const InstanceChannels = lazy(() =>
  import('../../pages/tenant/InstanceChannels').then((m) => ({ default: m.InstanceChannels }))
);
export const InstanceFiles = lazy(() =>
  import('../../pages/tenant/InstanceFiles').then((m) => ({ default: m.InstanceFiles }))
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
export const EvolutionLog = lazy(() =>
  import('../../pages/tenant/EvolutionLog').then((m) => ({ default: m.EvolutionLog }))
);
export const GenomeDetail = lazy(() =>
  import('../../pages/tenant/GenomeDetail').then((m) => ({ default: m.GenomeDetail }))
);
export const TemplateDetail = lazy(() =>
  import('../../pages/tenant/TemplateDetail').then((m) => ({ default: m.TemplateDetail }))
);

// Admin pages
export const PoolDashboard = lazy(() => import('../../pages/admin/PoolDashboard'));
export const DeadLetterQueue = lazy(() => import('../../pages/admin/DeadLetterQueue'));

// Project pages
export const ProjectOverview = lazy(() =>
  import('../../pages/project/ProjectOverview').then((m) => ({
    default: m.ProjectOverview,
  }))
);
export const MemoryList = lazy(() =>
  import('../../pages/project/MemoryList').then((m) => ({ default: m.MemoryList }))
);
export const NewMemory = lazy(() =>
  import('../../pages/project/NewMemory').then((m) => ({ default: m.NewMemory }))
);
export const MemoryDetail = lazy(() =>
  import('../../pages/project/MemoryDetail').then((m) => ({
    default: m.MemoryDetail,
  }))
);
export const MemoryGraph = lazy(() =>
  import('../../pages/project/MemoryGraph').then((m) => ({
    default: m.MemoryGraph,
  }))
);
export const EntitiesList = lazy(() =>
  import('../../pages/project/EntitiesList').then((m) => ({
    default: m.EntitiesList,
  }))
);
export const CommunitiesList = lazy(() =>
  import('../../pages/project/CommunitiesList').then((m) => ({
    default: m.CommunitiesList as ComponentType,
  }))
);
export const EnhancedSearch = lazy(() =>
  import('../../pages/project/EnhancedSearch').then((m) => ({
    default: m.EnhancedSearch,
  }))
);
export const Maintenance = lazy(() =>
  import('../../pages/project/Maintenance').then((m) => ({
    default: m.Maintenance,
  }))
);
export const CronJobs = lazy(
  () =>
    import('../../pages/project/CronJobs').then((m) => ({ default: m.CronJobs })) as Promise<{
      default: ComponentType;
    }>
);
export const Team = lazy(() =>
  import('../../pages/project/Team').then((m) => ({ default: m.Team }))
);
export const ProjectSettings = lazy(() =>
  import('../../pages/project/Settings').then((m) => ({
    default: m.ProjectSettings,
  }))
);
export const Support = lazy(() =>
  import('../../pages/project/Support').then((m) => ({ default: m.Support }))
);
export const Blackboard = lazy(() =>
  import('../../pages/project/Blackboard').then((m) => ({ default: m.Blackboard }))
);
export const PlaybookLibrary = lazy(() =>
  import('../../pages/project/PlaybookLibrary').then((m) => ({ default: m.PlaybookLibrary }))
);

// Schema pages
export const SchemaOverview = lazy(() => import('../../pages/project/schema/SchemaOverview'));
export const EntityTypeList = lazy(() => import('../../pages/project/schema/EntityTypeList'));
export const EdgeTypeList = lazy(() => import('../../pages/project/schema/EdgeTypeList'));
export const EdgeMapList = lazy(() => import('../../pages/project/schema/EdgeMapList'));
