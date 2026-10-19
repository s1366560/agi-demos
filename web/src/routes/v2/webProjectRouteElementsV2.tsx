import { Suspense, type ReactNode } from 'react';

import { Navigate, Route } from 'react-router-dom';

import { SchemaLayout } from '../../layouts/SchemaLayout';

import {
  ProjectOverview,
  MemoryList,
  NewMemory,
  MemoryDetail,
  MemoryGraph,
  EntitiesList,
  CommunitiesList,
  EnhancedSearch,
  Maintenance,
  CronJobs,
  SchemaOverview,
  EntityTypeList,
  EdgeTypeList,
  EdgeMapList,
  Team,
  ProjectSettings,
  Support,
  Blackboard,
  PlaybookLibrary,
  WorkspaceList,
  WorkspaceCreate,
  WorkspaceBlackboardRedirect,
  ProjectAgentDashboard,
  ProjectAgentLogs,
  ProjectAgentPatterns,
} from './webDefaultRouteComponentsV2';
import { WebRoutePageLoaderV2 as PageLoader } from './WebRoutePageLoaderV2';
import { LegacyTenantConversationRedirect, ProjectChannelsRedirect } from './webRouteRedirectsV2';

export function createProjectRouteElementsV2(): ReactNode {
  return (
    <>
      <Route path=":tenantId/project/:projectId">
        <Route
          handle={{ pluginFeature: 'project-overview' }}
          index
          element={
            <Suspense fallback={<PageLoader />}>
              <ProjectOverview />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-memories' }}
          path="memories"
          element={
            <Suspense fallback={<PageLoader />}>
              <MemoryList />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-memories' }}
          path="memories/new"
          element={
            <Suspense fallback={<PageLoader />}>
              <NewMemory />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-memories' }}
          path="memory/:memoryId"
          element={
            <Suspense fallback={<PageLoader />}>
              <MemoryDetail />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-graph' }}
          path="graph"
          element={
            <Suspense fallback={<PageLoader />}>
              <MemoryGraph />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-entities' }}
          path="entities"
          element={
            <Suspense fallback={<PageLoader />}>
              <EntitiesList />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-communities' }}
          path="communities"
          element={
            <Suspense fallback={<PageLoader />}>
              <CommunitiesList />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-search' }}
          path="advanced-search"
          element={
            <Suspense fallback={<PageLoader />}>
              <EnhancedSearch />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-search' }}
          path="search"
          element={<Navigate to="advanced-search" replace />}
        />
        <Route
          handle={{ pluginFeature: 'project-maintenance' }}
          path="maintenance"
          element={
            <Suspense fallback={<PageLoader />}>
              <Maintenance />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-cron-jobs' }}
          path="cron-jobs"
          element={
            <Suspense fallback={<PageLoader />}>
              <CronJobs />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-schema' }}
          path="schema"
          element={<SchemaLayout />}
        >
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
        <Route
          handle={{ pluginFeature: 'project-channels' }}
          path="channels"
          element={<ProjectChannelsRedirect />}
        />
        <Route
          handle={{ pluginFeature: 'project-team' }}
          path="team"
          element={
            <Suspense fallback={<PageLoader />}>
              <Team />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-settings' }}
          path="settings"
          element={
            <Suspense fallback={<PageLoader />}>
              <ProjectSettings />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-support' }}
          path="support"
          element={
            <Suspense fallback={<PageLoader />}>
              <Support />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-blackboard' }}
          path="blackboard"
          element={
            <Suspense fallback={<PageLoader />}>
              <Blackboard />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-playbooks' }}
          path="playbooks"
          element={
            <Suspense fallback={<PageLoader />}>
              <PlaybookLibrary />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-workspaces' }}
          path="workspaces"
          element={
            <Suspense fallback={<PageLoader />}>
              <WorkspaceList />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-workspaces' }}
          path="workspaces/new"
          element={
            <Suspense fallback={<PageLoader />}>
              <WorkspaceCreate />
            </Suspense>
          }
        />
        <Route
          handle={{ pluginFeature: 'project-workspaces' }}
          path="workspaces/:workspaceId"
          element={
            <Suspense fallback={<PageLoader />}>
              <WorkspaceBlackboardRedirect />
            </Suspense>
          }
        />
        <Route path="agent">
          <Route
            handle={{ pluginFeature: 'project-agent-dashboard' }}
            index
            element={
              <Suspense fallback={<PageLoader />}>
                <ProjectAgentDashboard />
              </Suspense>
            }
          />
          <Route
            handle={{ pluginFeature: 'project-agent-logs' }}
            path="logs"
            element={
              <Suspense fallback={<PageLoader />}>
                <ProjectAgentLogs />
              </Suspense>
            }
          />
          <Route
            handle={{ pluginFeature: 'project-agent-patterns' }}
            path="patterns"
            element={
              <Suspense fallback={<PageLoader />}>
                <ProjectAgentPatterns />
              </Suspense>
            }
          />
        </Route>
      </Route>

      {/* Legacy tenant workspace/conversation routes must stay after known tenant pages. */}
      <Route
        handle={{ pluginFeature: 'tenant-agent-workspace' }}
        path=":tenantId/:conversation"
        element={
          <Suspense fallback={<PageLoader />}>
            <LegacyTenantConversationRedirect />
          </Suspense>
        }
      />
    </>
  );
}
