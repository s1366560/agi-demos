/**
 * Analytics Service
 *
 * Provides API client for tenant analytics data.
 */

import { httpClient } from './client/httpClient';

import type { ProjectStorage } from '@/types/analytics';

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

export interface AnalyticsService {
  getTenantAnalytics(tenantId: string, period?: string): Promise<TenantAnalytics>;
}

class AnalyticsServiceImpl implements AnalyticsService {
  /**
   * Get tenant analytics data
   *
   * GET /api/v1/tenants/{tenantId}/analytics
   */
  async getTenantAnalytics(tenantId: string, period: string = '30d'): Promise<TenantAnalytics> {
    return httpClient.get<TenantAnalytics>(`/tenants/${tenantId}/analytics`, {
      params: { period },
    });
  }
}

// Export singleton instance
export const analyticsService = new AnalyticsServiceImpl();
export default analyticsService;
