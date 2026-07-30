export type CloudProjectOverviewScope = Readonly<{
  authority: 'cloud';
  tenantId: string;
  projectId: string;
}>;

export type CloudProjectOverviewProject = Readonly<{
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
}>;

export type CloudProjectOverviewStats = Readonly<{
  memory_count: number;
  storage_used: number;
  storage_limit: number;
  active_nodes: number;
  collaborators: number;
}>;

export type CloudProjectOverviewMemory = Readonly<{
  id: string;
  project_id: string;
  title: string;
  content: string;
  content_type: string;
  status: string;
  metadata: Readonly<Record<string, unknown>>;
  created_at: string;
  updated_at: string | null;
}>;

export type CloudProjectOverviewMemoryQuery = Readonly<{
  page: 1;
  page_size: 5;
}>;

export type CloudProjectOverviewMemoryPage = Readonly<{
  memories: readonly CloudProjectOverviewMemory[];
  total: number;
  page: number;
  page_size: number;
}>;

export type CloudProjectOverviewReadOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type CloudProjectOverviewSnapshot = Readonly<{
  scope: CloudProjectOverviewScope;
  project: CloudProjectOverviewProject;
  stats: CloudProjectOverviewStats;
  latestMemories: readonly CloudProjectOverviewMemory[];
  latestMemoriesTotal: number;
}>;

export type CloudProjectOverviewReadResult =
  | Readonly<{ kind: 'ready'; snapshot: CloudProjectOverviewSnapshot }>
  | Readonly<{ kind: 'empty' }>;

// Local Project Overview must use a separate availability-bearing projection. It must not
// implement this Cloud port by fabricating Memory, quota, node, or collaborator values.
export interface CloudProjectOverviewClient {
  getProject(
    scope: CloudProjectOverviewScope,
    options?: CloudProjectOverviewReadOptions,
  ): Promise<CloudProjectOverviewProject | null>;
  getProjectStats(
    scope: CloudProjectOverviewScope,
    options?: CloudProjectOverviewReadOptions,
  ): Promise<CloudProjectOverviewStats>;
  listMemories(
    scope: CloudProjectOverviewScope,
    query: CloudProjectOverviewMemoryQuery,
    options?: CloudProjectOverviewReadOptions,
  ): Promise<CloudProjectOverviewMemoryPage>;
}

export const CLOUD_PROJECT_OVERVIEW_LATEST_MEMORIES_QUERY: CloudProjectOverviewMemoryQuery =
  Object.freeze({
    page: 1,
    page_size: 5,
  });

export async function readCloudProjectOverview(
  client: CloudProjectOverviewClient,
  scope: CloudProjectOverviewScope,
  options?: CloudProjectOverviewReadOptions,
): Promise<CloudProjectOverviewReadResult> {
  const [project, stats, memoryPage] = await Promise.all([
    client.getProject(scope, options),
    client.getProjectStats(scope, options),
    client.listMemories(scope, CLOUD_PROJECT_OVERVIEW_LATEST_MEMORIES_QUERY, options),
  ]);
  if (project === null) return { kind: 'empty' };

  return {
    kind: 'ready',
    snapshot: {
      scope,
      project,
      stats,
      latestMemories: memoryPage.memories,
      latestMemoriesTotal: memoryPage.total,
    },
  };
}
