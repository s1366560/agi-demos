/**
 * Analytics Types
 */

export interface ProjectStorage {
  name: string;
  storage_bytes: number;
  memory_count: number;
}

export interface MemoryGrowthPoint {
  date: string;
  count: number;
}

export interface AnalyticsSummary {
  total_memories: number;
  total_storage_bytes: number;
  total_projects: number;
  period_days: number;
}

export interface TenantAnalytics {
  memoryGrowth: MemoryGrowthPoint[];
  projectStorage: ProjectStorage[];
  summary: AnalyticsSummary;
}
