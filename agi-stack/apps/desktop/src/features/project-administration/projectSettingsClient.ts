import type {
  ProjectAdministrationOptions,
  ProjectAdministrationScope,
  ProjectAdministrationSnapshotBase,
} from './projectAdministrationClient';

export const PROJECT_SETTINGS_ROUTE_ID = 'project-project-settings' as const;
export const PROJECT_SETTINGS_LOCAL_REASON = 'local_project_settings_authority_unavailable' as const;
export const PROJECT_SETTINGS_DEGRADED_REASON = 'desktop_project_settings_actions_unwired' as const;

export type ProjectSettingsProject = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  description: string | null;
  ownerId: string;
  isPublic: boolean;
  memoryRules: Readonly<{
    maxEpisodes: number;
    retentionDays: number;
    autoRefresh: boolean;
    refreshInterval: number;
  }>;
  graphConfig: Readonly<{
    maxNodes: number;
    maxEdges: number;
    similarityThreshold: number;
    communityDetection: boolean;
  }>;
  sandboxType: string;
  conversationMode: string;
  createdAt: string;
  updatedAt: string | null;
}>;
export type ProjectSettingsSandbox = Readonly<{
  id: string;
  status: string;
  healthy: boolean;
  createdAt: string;
}>;
export type ProjectSettingsSandboxStats = Readonly<{
  sandboxId: string;
  status: string;
  cpuPercent: number;
  memoryUsage: number;
  memoryLimit: number;
  memoryPercent: number;
  pids: number;
  collectedAt: string;
}>;
export type ProjectSettingsSnapshot = ProjectAdministrationSnapshotBase &
  Readonly<{
    project: ProjectSettingsProject;
    sandbox: ProjectSettingsSandbox | null;
    sandboxStats: ProjectSettingsSandboxStats | null;
  }>;
export type ProjectSettingsClient = Readonly<{
  load(
    scope: ProjectAdministrationScope,
    options?: ProjectAdministrationOptions,
  ): Promise<ProjectSettingsSnapshot>;
}>;
