import type { DesktopRuntimeConfig } from '@desktop/types';
import type { DesktopProjectBlackboardOperationsV2 } from '@desktop/plugins/desktopProjectBlackboardAuthorityModuleV2';
import type { WorkspaceCollaborationSurface } from '@desktop/features/workspace/workspaceCollaborationClient';

export type ProjectBlackboardAuthority = 'cloud' | 'local';

export type ProjectBlackboardScope = Readonly<{
  authority: ProjectBlackboardAuthority;
  tenantId: string;
  projectId: string;
  workspaceId: string;
}>;

export type ProjectBlackboardSnapshot = Readonly<{
  scope: ProjectBlackboardScope;
  authority: ProjectBlackboardAuthority;
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  initialSurface: WorkspaceCollaborationSurface;
  allowedActions: readonly string[];
  authorityRevision: number | null;
}>;

export interface ProjectBlackboardClient {
  probe(scope: ProjectBlackboardScope, signal?: AbortSignal): Promise<ProjectBlackboardSnapshot>;
}

export function createProjectBlackboardV2Client(
  config: DesktopRuntimeConfig,
  operations: Pick<DesktopProjectBlackboardOperationsV2, 'probeProjectBlackboard'>,
): ProjectBlackboardClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ProjectBlackboardClient = {
    probe: (scope: ProjectBlackboardScope, signal?: AbortSignal) =>
      operations.probeProjectBlackboard({
        config: runtimeConfig,
        scope,
        ...(signal === undefined ? {} : { signal }),
      }),
  };
  return Object.freeze(client);
}
