import {
  type ProjectKnowledgeClient,
  type ProjectKnowledgeSnapshotBase,
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
} from './projectKnowledgeClient';
import type { CloudMemoryCapabilities } from './cloudMemoryCapabilities';

export const PROJECT_MEMORIES_ROUTE_ID = 'project-project-memories' as const;
export const PROJECT_MEMORIES_LOCAL_REASON =
  'local_project_memories_authority_unavailable' as const;
export const PROJECT_MEMORIES_DEGRADED_REASON = 'desktop_project_memories_actions_partial' as const;

export type ProjectMemory = Readonly<{
  id: string;
  projectId: string;
  title: string;
  content: string;
  contentType: string;
  version: number;
  status: string;
  processingStatus: string;
  createdAt: string;
  updatedAt: string | null;
}>;
export type ProjectMemoriesSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{
    memories: readonly ProjectMemory[];
    page: number;
    pageSize: number;
    commandCapabilities?: CloudMemoryCapabilities | null;
  }> &
  (Readonly<{ total: number }> | Readonly<{ total: null; hasMore: boolean }>);
export type ProjectMemoriesPageOptions = Readonly<{
  page?: number;
  pageSize?: number;
}>;
export interface ProjectMemoriesClient extends ProjectKnowledgeClient<ProjectMemoriesSnapshot> {
  load(
    scope: ProjectKnowledgeScope,
    options?: ProjectKnowledgeReadOptions & ProjectMemoriesPageOptions,
  ): Promise<ProjectMemoriesSnapshot>;
}
