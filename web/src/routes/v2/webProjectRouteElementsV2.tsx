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
          index
          element={
            <Suspense fallback={<PageLoader />}>
              <ProjectOverview />
            </Suspense>
          }
        />
        <Route
          path="memories"
          element={
            <Suspense fallback={<PageLoader />}>
              <MemoryList />
            </Suspense>
          }
        />
        <Route
          path="memories/new"
          element={
            <Suspense fallback={<PageLoader />}>
              <NewMemory />
            </Suspense>
          }
        />
        <Route
          path="memory/:memoryId"
          element={
            <Suspense fallback={<PageLoader />}>
              <MemoryDetail />
            </Suspense>
          }
        />
        <Route
          path="graph"
          element={
            <Suspense fallback={<PageLoader />}>
              <MemoryGraph />
            </Suspense>
          }
        />
        <Route
          path="entities"
          element={
            <Suspense fallback={<PageLoader />}>
              <EntitiesList />
            </Suspense>
          }
        />
        <Route
          path="communities"
          element={
            <Suspense fallback={<PageLoader />}>
              <CommunitiesList />
            </Suspense>
          }
        />
        <Route
          path="advanced-search"
          element={
            <Suspense fallback={<PageLoader />}>
              <EnhancedSearch />
            </Suspense>
          }
        />
        <Route path="search" element={<Navigate to="advanced-search" replace />} />
        <Route
          path="maintenance"
          element={
            <Suspense fallback={<PageLoader />}>
              <Maintenance />
            </Suspense>
          }
        />
        <Route
          path="cron-jobs"
          element={
            <Suspense fallback={<PageLoader />}>
              <CronJobs />
            </Suspense>
          }
        />
        <Route path="schema" element={<SchemaLayout />}>
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
        <Route path="channels" element={<ProjectChannelsRedirect />} />
        <Route
          path="team"
          element={
            <Suspense fallback={<PageLoader />}>
              <Team />
            </Suspense>
          }
        />
        <Route
          path="settings"
          element={
            <Suspense fallback={<PageLoader />}>
              <ProjectSettings />
            </Suspense>
          }
        />
        <Route
          path="support"
          element={
            <Suspense fallback={<PageLoader />}>
              <Support />
            </Suspense>
          }
        />
        <Route
          path="blackboard"
          element={
            <Suspense fallback={<PageLoader />}>
              <Blackboard />
            </Suspense>
          }
        />
        <Route
          path="playbooks"
          element={
            <Suspense fallback={<PageLoader />}>
              <PlaybookLibrary />
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
          path="workspaces/:workspaceId"
          element={
            <Suspense fallback={<PageLoader />}>
              <WorkspaceBlackboardRedirect />
            </Suspense>
          }
        />
        <Route path="agent">
          <Route
            index
            element={
              <Suspense fallback={<PageLoader />}>
                <ProjectAgentDashboard />
              </Suspense>
            }
          />
          <Route
            path="logs"
            element={
              <Suspense fallback={<PageLoader />}>
                <ProjectAgentLogs />
              </Suspense>
            }
          />
          <Route
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
