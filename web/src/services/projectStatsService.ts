/**
 * Service for fetching project context data (stats, trending, skills).
 */

import { apiFetch } from './client/urlUtils';

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
    const res = await apiFetch.get(`/projects/${projectId}/stats`);
    return (await res.json()) as ProjectStats;
  },

  async getTrending(projectId: string, limit = 10): Promise<TrendingEntity[]> {
    const res = await apiFetch.get(`/projects/${projectId}/trending?limit=${String(limit)}`);
    const data = (await res.json()) as { entities: TrendingEntity[] };
    return data.entities;
  },

  async getRecentSkills(projectId: string, limit = 5): Promise<RecentSkill[]> {
    const res = await apiFetch.get(`/projects/${projectId}/recent-skills?limit=${String(limit)}`);
    const data = (await res.json()) as { skills: RecentSkill[] };
    return data.skills;
  },
};
