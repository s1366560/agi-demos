import type { DesktopRuntimeConfig, RuntimeDataset, WorkspaceAuthorityCollection } from '../../types';

export function beginWorkspaceRuntimeTransition(dataset: RuntimeDataset): RuntimeDataset {
  return {
    ...dataset,
    messages: [],
    tasks: [],
    plan: null,
    workspaceMembers: unavailableAuthorityCollection(),
    workspaceAgents: unavailableAuthorityCollection(),
  };
}

export function beginDesktopRuntimeScopeTransition(
  dataset: RuntimeDataset,
  previousConfig: DesktopRuntimeConfig,
  nextConfig: DesktopRuntimeConfig,
): RuntimeDataset {
  if (!sameProjectRuntimeScope(previousConfig, nextConfig)) {
    return {
      workspaces: [],
      workspacesByProject: {},
      conversationsByWorkspace: {},
      nodeState: { projects: {}, workspaces: {} },
      messages: [],
      tasks: [],
      plan: null,
      workspaceMembers: unavailableAuthorityCollection(),
      workspaceAgents: unavailableAuthorityCollection(),
      sandbox: null,
      myWork: [],
      myWorkError: null,
    };
  }
  if (previousConfig.workspaceId !== nextConfig.workspaceId) {
    return beginWorkspaceRuntimeTransition(dataset);
  }
  return dataset;
}

function unavailableAuthorityCollection<T>(): WorkspaceAuthorityCollection<T> {
  return { status: 'unavailable', items: [], error: null };
}

function sameProjectRuntimeScope(
  previousConfig: DesktopRuntimeConfig,
  nextConfig: DesktopRuntimeConfig,
): boolean {
  return (
    previousConfig.mode === nextConfig.mode &&
    previousConfig.apiBaseUrl === nextConfig.apiBaseUrl &&
    previousConfig.apiKey === nextConfig.apiKey &&
    previousConfig.localApiToken === nextConfig.localApiToken &&
    previousConfig.tenantId === nextConfig.tenantId &&
    previousConfig.projectId === nextConfig.projectId
  );
}
