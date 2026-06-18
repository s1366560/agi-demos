/**
 * Service for fetching project context data (stats, trending, skills).
 */

import { apiFetch } from './client/urlUtils';

const PROJECT_SUMMARY_CACHE_TTL_MS = 10_000;

interface ProjectSummaryRequest<T> {
  promise: Promise<T>;
  expiresAt: number;
  pending: boolean;
}

const projectSummaryRequests = new Map<string, ProjectSummaryRequest<unknown>>();

function buildSummaryKey(kind: string, projectId: string, limit?: number): string {
  return JSON.stringify([kind, projectId, limit ?? null]);
}

function loadProjectSummary<T>(key: string, loader: () => Promise<T>): Promise<T> {
  const existing = projectSummaryRequests.get(key);
  const now = Date.now();

  if (existing) {
    if (existing.pending || existing.expiresAt > now) {
      return existing.promise as Promise<T>;
    }
    projectSummaryRequests.delete(key);
  }

  const entry: ProjectSummaryRequest<T> = {
    pending: true,
    expiresAt: Number.POSITIVE_INFINITY,
    promise: Promise.resolve(undefined as T),
  };

  entry.promise = loader()
    .then((data) => {
      entry.pending = false;
      entry.expiresAt = Date.now() + PROJECT_SUMMARY_CACHE_TTL_MS;
      return data;
    })
    .catch((error: unknown) => {
      projectSummaryRequests.delete(key);
      throw error;
    });

  projectSummaryRequests.set(key, entry as ProjectSummaryRequest<unknown>);
  return entry.promise;
}

export interface ProjectStats {
  memory_count: number;
  conversation_count: number;
  node_count: number;
  member_count: number;
  active_nodes: number;
  storage_used: number;
  storage_limit: number;
}

export interface TrendingEntity {
  name: string;
  entity_type: string;
  mention_count: number;
  summary?: string | undefined;
}

export interface RecentSkill {
  name: string;
  last_used: string;
  usage_count: number;
}

export const projectStatsService = {
  async getStats(projectId: string): Promise<ProjectStats> {
    return loadProjectSummary(buildSummaryKey('stats', projectId), async () => {
      const res = await apiFetch.get(`/projects/${projectId}/stats`);
      return (await res.json()) as ProjectStats;
    });
  },

  async getTrending(projectId: string, limit = 10): Promise<TrendingEntity[]> {
    return loadProjectSummary(buildSummaryKey('trending', projectId, limit), async () => {
      const res = await apiFetch.get(`/projects/${projectId}/trending?limit=${String(limit)}`);
      const data = (await res.json()) as { entities: TrendingEntity[] };
      return data.entities;
    });
  },

  async getRecentSkills(projectId: string, limit = 5): Promise<RecentSkill[]> {
    return loadProjectSummary(buildSummaryKey('recent-skills', projectId, limit), async () => {
      const res = await apiFetch.get(`/projects/${projectId}/recent-skills?limit=${String(limit)}`);
      const data = (await res.json()) as { skills: RecentSkill[] };
      return data.skills;
    });
  },
};

export function clearProjectStatsSummaryCache(): void {
  projectSummaryRequests.clear();
}
