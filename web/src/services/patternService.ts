/**
 * Pattern service for managing workflow patterns.
 *
 * Workflow patterns are tenant-scoped - shared across all projects
 * within a tenant but isolated between tenants.
 *
 * API Endpoints:
 * - GET /agent/workflows/patterns - List patterns for tenant
 * - GET /agent/workflows/patterns/{id} - Get pattern by ID
 * - DELETE /agent/workflows/patterns/{id} - Delete pattern
 * - POST /agent/workflows/patterns/reset - Reset all patterns
 */

import axios from 'axios';
import { httpClient } from './client/httpClient';
import type {
  WorkflowPattern,
  PatternsListResponse,
  ResetPatternsResponse,
} from '../types/agent';

// Use centralized HTTP client
const api = httpClient;

/**
 * Options for listing patterns
 */
export interface ListPatternsOptions {
  page?: number;
  pageSize?: number;
  minSuccessRate?: number;
}

/**
 * Pattern service error
 */
export class PatternServiceError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public code?: string
  ) {
    super(message);
    this.name = 'PatternServiceError';
  }
}

/**
 * Pattern service interface
 */
export interface PatternService {
  listPatterns(tenantId: string, options?: ListPatternsOptions): Promise<PatternsListResponse>;
  getPattern(patternId: string, tenantId: string): Promise<WorkflowPattern>;
  deletePattern(patternId: string, tenantId: string): Promise<void>;
  resetPatterns(tenantId: string): Promise<ResetPatternsResponse>;
}

/**
 * Pattern service implementation
 */
class PatternServiceImpl implements PatternService {
  /**
   * List workflow patterns for a tenant
   */
  async listPatterns(
    tenantId: string,
    options: ListPatternsOptions = {}
  ): Promise<PatternsListResponse> {
    const { page = 1, pageSize = 50, minSuccessRate } = options;

    const params: Record<string, string | number> = {
      tenant_id: tenantId,
      page,
      page_size: pageSize,
    };

    if (minSuccessRate !== undefined) {
      params.min_success_rate = minSuccessRate;
    }

    try {
      const response = await api.get<PatternsListResponse>(
        '/agent/workflows/patterns',
        { params }
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status;
        const message = error.response?.data?.detail || error.message;

        if (status === 403) {
          throw new PatternServiceError('Access denied to tenant patterns', status, 'FORBIDDEN');
        }
        if (status === 404) {
          throw new PatternServiceError('Tenant not found', status, 'NOT_FOUND');
        }

        throw new PatternServiceError(message, status);
      }
      throw error;
    }
  }

  /**
   * Get a workflow pattern by ID
   */
  async getPattern(patternId: string, tenantId: string): Promise<WorkflowPattern> {
    try {
      const response = await api.get<WorkflowPattern>(
        `/agent/workflows/patterns/${patternId}`,
        { params: { tenant_id: tenantId } }
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status;
        const message = error.response?.data?.detail || error.message;

        if (status === 403) {
          throw new PatternServiceError('Access denied to pattern', status, 'FORBIDDEN');
        }
        if (status === 404) {
          throw new PatternServiceError('Pattern not found', status, 'NOT_FOUND');
        }

        throw new PatternServiceError(message, status);
      }
      throw error;
    }
  }

  /**
   * Delete a workflow pattern (Admin only)
   */
  async deletePattern(patternId: string, tenantId: string): Promise<void> {
    try {
      await api.delete(`/agent/workflows/patterns/${patternId}`, {
        params: { tenant_id: tenantId },
      });
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status;
        const message = error.response?.data?.detail || error.message;

        if (status === 403) {
          throw new PatternServiceError('Admin access required to delete patterns', status, 'FORBIDDEN');
        }
        if (status === 404) {
          throw new PatternServiceError('Pattern not found', status, 'NOT_FOUND');
        }

        throw new PatternServiceError(message, status);
      }
      throw error;
    }
  }

  /**
   * Reset all workflow patterns for a tenant (Admin only)
   *
   * WARNING: This is a destructive operation that removes all learned patterns.
   */
  async resetPatterns(tenantId: string): Promise<ResetPatternsResponse> {
    try {
      const response = await api.post<ResetPatternsResponse>(
        '/agent/workflows/patterns/reset',
        null,
        { params: { tenant_id: tenantId } }
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status;
        const message = error.response?.data?.detail || error.message;

        if (status === 403) {
          throw new PatternServiceError('Admin access required to reset patterns', status, 'FORBIDDEN');
        }

        throw new PatternServiceError(message, status);
      }
      throw error;
    }
  }
}

// Export singleton instance
export const patternService = new PatternServiceImpl();
export default patternService;
