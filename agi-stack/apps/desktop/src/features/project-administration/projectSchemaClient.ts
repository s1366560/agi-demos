import {
  type ProjectAdministrationOptions,
  type ProjectAdministrationScope,
  type ProjectAdministrationSnapshotBase,
} from './projectAdministrationClient';

export const PROJECT_SCHEMA_ROUTE_ID = 'project-project-schema' as const;
export const PROJECT_SCHEMA_LOCAL_REASON = 'local_project_schema_authority_unavailable' as const;
export const PROJECT_SCHEMA_DEGRADED_REASON =
  'desktop_project_schema_actions_and_export_unwired' as const;

export type ProjectSchemaType = Readonly<{
  id: string;
  projectId: string;
  name: string;
  description: string | null;
  schema: Readonly<Record<string, unknown>>;
  status: string;
  source: string;
  createdAt: string;
  updatedAt: string | null;
}>;
export type ProjectSchemaMapping = Readonly<{
  id: string;
  projectId: string;
  sourceType: string;
  targetType: string;
  edgeType: string;
  status: string;
  source: string;
  createdAt: string;
}>;
export type ProjectSchemaSnapshot = ProjectAdministrationSnapshotBase &
  Readonly<{
    entityTypes: readonly ProjectSchemaType[];
    edgeTypes: readonly ProjectSchemaType[];
    mappings: readonly ProjectSchemaMapping[];
  }>;
export type ProjectSchemaClient = Readonly<{
  load(
    scope: ProjectAdministrationScope,
    options?: ProjectAdministrationOptions,
  ): Promise<ProjectSchemaSnapshot>;
}>;
