import type {
  ProjectAgentReadOptions,
  ProjectAgentScope,
  ProjectAgentSnapshotBase,
} from './projectAgentClient';

export const PROJECT_AGENT_PATTERNS_ROUTE_ID = 'project-agent-patterns' as const;
export const PROJECT_AGENT_PATTERNS_LOCAL_REASON =
  'local_project_agent_patterns_authority_unavailable' as const;

export type ProjectAgentPattern = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  description: string;
  successRate: number;
  usageCount: number;
  createdAt: string;
}>;
export type ProjectAgentPatternsSnapshot = ProjectAgentSnapshotBase &
  Readonly<{
    scopeKind: 'tenant_shared';
    patterns: readonly ProjectAgentPattern[];
    total: number;
  }>;
export type ProjectAgentPatternsClient = Readonly<{
  load(
    scope: ProjectAgentScope,
    options?: ProjectAgentReadOptions,
  ): Promise<ProjectAgentPatternsSnapshot>;
}>;
