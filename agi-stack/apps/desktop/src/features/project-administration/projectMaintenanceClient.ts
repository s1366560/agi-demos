import type {
  ProjectAdministrationOptions,
  ProjectAdministrationScope,
  ProjectAdministrationSnapshotBase,
} from './projectAdministrationClient';

export const PROJECT_MAINTENANCE_ROUTE_ID = 'project-project-maintenance' as const;
export const PROJECT_MAINTENANCE_LOCAL_REASON =
  'local_project_maintenance_authority_unavailable' as const;
export const PROJECT_MAINTENANCE_DEGRADED_REASON =
  'desktop_project_maintenance_surface_and_endpoints_incomplete' as const;

export type ProjectMaintenanceStats = Readonly<{
  entityCount: number;
  episodeCount: number;
  communityCount: number;
  edgeCount: number;
}>;
export type ProjectMaintenanceStatus = Readonly<{
  entities: number;
  episodes: number;
  communities: number;
  oldEpisodes: number;
  recommendations: readonly string[];
  lastChecked: string;
}>;
export type ProjectEmbeddingStatus = Readonly<{
  currentProvider: string;
  currentDimension: number;
  existingDimension: number;
  compatible: boolean;
  missingEmbeddings: number;
}>;
export type ProjectMaintenanceSnapshot = ProjectAdministrationSnapshotBase &
  Readonly<{
    stats: ProjectMaintenanceStats;
    maintenanceStatus: ProjectMaintenanceStatus;
    embeddingStatus: ProjectEmbeddingStatus;
  }>;
export type ProjectMaintenanceClient = Readonly<{
  load(
    scope: ProjectAdministrationScope,
    options?: ProjectAdministrationOptions,
  ): Promise<ProjectMaintenanceSnapshot>;
}>;
