/**
 * Service for fetching project context data (stats, trending, skills).
 */

import { runWebOperationV2, type WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';

import { apiFetch } from './client/urlUtils';

const PROJECT_SUMMARY_CACHE_TTL_MS = 10_000;

interface ProjectSummaryRequest<T> {
  promise: Promise<T>;
  expiresAt: number;
  pending: boolean;
  signal: AbortSignal;
}

let projectSummaryRequests = new WeakMap<object, Map<string, ProjectSummaryRequest<unknown>>>();

function buildSummaryKey(kind: string, projectId: string, limit?: number): string {
  return JSON.stringify([kind, projectId, limit ?? null]);
}

function loadProjectSummary<T>(
  key: string,
  loader: (operation: WebOperationContextV2) => Promise<T>
): Promise<T> {
  return runWebOperationV2(async (operation) => {
    operation.check();
    let requests = projectSummaryRequests.get(operation.owner);
    if (!requests) {
      requests = new Map();
      projectSummaryRequests.set(operation.owner, requests);
    }
    const existing = requests.get(key);
    if (
      existing &&
      !existing.signal.aborted &&
      (existing.pending || existing.expiresAt > Date.now())
    ) {
      return existing.promise as Promise<T>;
    }
    const entry: ProjectSummaryRequest<T> = {
      pending: true,
      expiresAt: Number.POSITIVE_INFINITY,
      signal: operation.signal,
      promise: Promise.resolve(undefined as T),
    };
    const ownedRequests = requests;
    entry.promise = Promise.resolve()
      .then(() => {
        operation.check();
        return loader(operation);
      })
      .then((data) => {
        operation.check();
        entry.pending = false;
        entry.expiresAt = Date.now() + PROJECT_SUMMARY_CACHE_TTL_MS;
        return data;
      })
      .catch((error: unknown) => {
        // An older failed request must not remove a replacement admitted after cancellation.
        if (ownedRequests.get(key) === entry) ownedRequests.delete(key);
        throw error;
      });
    ownedRequests.set(key, entry as ProjectSummaryRequest<unknown>);
    return entry.promise;
  });
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
    return loadProjectSummary(buildSummaryKey('stats', projectId), async (operation) => {
      return apiFetch.get(
        `/projects/${projectId}/stats`,
        async (res) => {
          return (await res.json()) as ProjectStats;
        },
        { parent: operation, signal: operation.signal }
      );
    });
  },

  async getTrending(projectId: string, limit = 10): Promise<TrendingEntity[]> {
    return loadProjectSummary(buildSummaryKey('trending', projectId, limit), async (operation) => {
      return apiFetch.get(
        `/projects/${projectId}/trending?limit=${String(limit)}`,
        async (res) => {
          const data = (await res.json()) as { entities: TrendingEntity[] };
          return data.entities;
        },
        { parent: operation, signal: operation.signal }
      );
    });
  },

  async getRecentSkills(projectId: string, limit = 5): Promise<RecentSkill[]> {
    return loadProjectSummary(
      buildSummaryKey('recent-skills', projectId, limit),
      async (operation) => {
        return apiFetch.get(
          `/projects/${projectId}/recent-skills?limit=${String(limit)}`,
          async (res) => {
            const data = (await res.json()) as { skills: RecentSkill[] };
            return data.skills;
          },
          { parent: operation, signal: operation.signal }
        );
      }
    );
  },
};

export function clearProjectStatsSummaryCache(): void {
  projectSummaryRequests = new WeakMap();
}
