import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  createDesktopProjectBlackboardAuthorityV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopProjectBlackboardTransportV2.js');

export function projectBlackboardOperationsV2Fixture(overrides = {}) {
  const operations = {
    probeWorkspaceCollaborationCapability: ({ config, signal }) =>
      createDesktopProjectBlackboardAuthorityV2(config).probeWorkspaceCollaborationCapability(
        Object.freeze({
          tenantId: config.tenantId,
          projectId: config.projectId,
          workspaceId: config.workspaceId,
        }),
        signal,
      ),
    probeProjectBlackboard: ({ config, scope, signal }) =>
      createDesktopProjectBlackboardAuthorityV2(config).probeProjectBlackboard(scope, signal),
    getWorkspaceSurface: ({ config, projection, workspaceId, surface, cursor, signal }) =>
      createDesktopProjectBlackboardAuthorityV2(config).getWorkspaceSurface(
        projection,
        workspaceId,
        surface,
        cursor,
        signal,
      ),
    refetchWorkspaceSurface: ({ config, projection, workspaceId, surface, signal }) =>
      createDesktopProjectBlackboardAuthorityV2(config).refetchWorkspaceSurface(
        projection,
        workspaceId,
        surface,
        signal,
      ),
    mutateWorkspaceSurface: ({ config, projection, workspaceId, surface, mutation, signal }) =>
      createDesktopProjectBlackboardAuthorityV2(config).mutateWorkspaceSurface(
        projection,
        workspaceId,
        surface,
        mutation,
        signal,
      ),
  };
  return Object.freeze({ ...operations, ...overrides });
}
