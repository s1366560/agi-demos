import { Suspense, type ReactNode } from 'react';

import { Route } from 'react-router-dom';

import {
  TenantOverview,
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
  WorkflowPatterns,
  TaskDashboard,
  WorkspaceList,
  WorkspaceCreate,
  AgentDashboard,
  AgentWorkspace,
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
  OrgSettingsLayout,
  OrgInfo,
  OrgMembers,
  OrgClusters,
  OrgAudit,
  OrgRegistry,
  OrgSmtp,
  OrgGenes,
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
import { LegacyTenantSingleSegmentRedirect } from './webRouteRedirectsV2';

export function createTenantGenericRouteElementsV2(): ReactNode {
  return (
    <>
      <Route
        index
        element={
          <Suspense fallback={<PageLoader />}>
            <TenantOverview />
          </Suspense>
        }
      />
      <Route
        path=":segment"
        element={
          <Suspense fallback={<PageLoader />}>
            <LegacyTenantSingleSegmentRedirect />
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
        path="projects/:projectId/edit"
        element={
          <Suspense fallback={<PageLoader />}>
            <EditProject />
          </Suspense>
        }
      />
      <Route
        path="backend-stores"
        element={
          <Suspense fallback={<PageLoader />}>
            <BackendStores />
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
        path="patterns"
        element={
          <Suspense fallback={<PageLoader />}>
            <WorkflowPatterns />
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
        path="agent-definitions/:definitionId"
        element={
          <Suspense fallback={<PageLoader />}>
            <AgentDefinitionDetail />
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
        path="evolution"
        element={
          <Suspense fallback={<PageLoader />}>
            <SkillEvolution />
          </Suspense>
        }
      />
      <Route
        path="skills/:skillId"
        element={
          <Suspense fallback={<PageLoader />}>
            <SkillDetail />
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
        path="plugins/:pluginName"
        element={
          <Suspense fallback={<PageLoader />}>
            <PluginDetail />
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
        path="acp"
        element={
          <Suspense fallback={<PageLoader />}>
            <AcpDashboard />
          </Suspense>
        }
      />
      <Route
        path="pool"
        element={
          <Suspense fallback={<PageLoader />}>
            <PoolDashboard />
          </Suspense>
        }
      />
      <Route
        path="runtimes"
        element={
          <Suspense fallback={<PageLoader />}>
            <UnifiedRuntimes />
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
        path="dead-letter-queue"
        element={
          <Suspense fallback={<PageLoader />}>
            <DeadLetterQueue />
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
    </>
  );
}
