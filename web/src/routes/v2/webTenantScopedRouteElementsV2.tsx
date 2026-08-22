import { Suspense, type ReactNode } from 'react';

import { Navigate, Route } from 'react-router-dom';

import {
  TenantOverview,
  TaskDashboard,
  WorkspaceList,
  WorkspaceCreate,
  AgentDashboard,
  AgentWorkspace,
  ProjectList,
  NewProject,
  EditProject,
  BackendStores,
  UserList,
  ProviderList,
  UserProfile,
  Analytics,
  Events,
  Webhooks,
  Billing,
  TenantSettings,
  OrgSettingsLayout,
  OrgInfo,
  OrgMembers,
  OrgClusters,
  OrgAudit,
  OrgRegistry,
  OrgSmtp,
  OrgGenes,
  WorkflowPatterns,
  SubAgentList,
  AgentDefinitions,
  AgentDefinitionDetail,
  AgentBindings,
  SkillList,
  SkillEvolution,
  SkillDetail,
  TemplateMarketplace,
  PluginHub,
  PluginDetail,
  McpServerList,
  AcpDashboard,
  PoolDashboard,
  UnifiedRuntimes,
  InstanceList,
  CreateInstance,
  InstanceLayout,
  InstanceOverview,
  InstanceFiles,
  InstanceChannels,
  InstanceMembers,
  InstanceGenes,
  InstanceSettings,
  DeployProgress,
  AuditLogs,
  DeadLetterQueue,
  TrustPolicies,
  DecisionRecords,
  ClusterList,
  ClusterDetail,
  GeneMarket,
  GeneDetail,
  InstanceTemplateList,
  TemplateDetail,
  EvolutionLog,
  GenomeDetail,
} from './webDefaultRouteComponentsV2';
import { WebRoutePageLoaderV2 as PageLoader } from './WebRoutePageLoaderV2';

export function createTenantScopedRouteElementsV2(): ReactNode {
  return (
    <>
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
        path=":tenantId/backend-stores"
        element={
          <Suspense fallback={<PageLoader />}>
            <BackendStores />
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
        path=":tenantId/profile"
        element={
          <Suspense fallback={<PageLoader />}>
            <UserProfile />
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
        path=":tenantId/agent-definitions/:definitionId"
        element={
          <Suspense fallback={<PageLoader />}>
            <AgentDefinitionDetail />
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
        path=":tenantId/evolution"
        element={
          <Suspense fallback={<PageLoader />}>
            <SkillEvolution />
          </Suspense>
        }
      />
      <Route
        path=":tenantId/skills/:skillId"
        element={
          <Suspense fallback={<PageLoader />}>
            <SkillDetail />
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
        path=":tenantId/plugins/:pluginName"
        element={
          <Suspense fallback={<PageLoader />}>
            <PluginDetail />
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
        path=":tenantId/acp"
        element={
          <Suspense fallback={<PageLoader />}>
            <AcpDashboard />
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
        path=":tenantId/runtimes"
        element={
          <Suspense fallback={<PageLoader />}>
            <UnifiedRuntimes />
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
        path=":tenantId/dead-letter-queue"
        element={
          <Suspense fallback={<PageLoader />}>
            <DeadLetterQueue />
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
    </>
  );
}
