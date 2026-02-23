/**
 * Tenant Agent Configuration Service (T103, T089)
 *
 * Provides API client for tenant-level agent configuration.
 *
 * Features:
 * - Get tenant config (returns default if not set)
 * - Update tenant config (admin only)
 * - Check modification permissions
 *
 * Access Control (FR-021, FR-022):
 * - All authenticated users can read config
 * - Only tenant admins can modify config
 */

import { ApiError } from './client/ApiError';
import { httpClient } from './client/httpClient';

import type {
  TenantAgentConfig,
  TenantAgentConfigService as ITenantAgentConfigService,
  UpdateTenantAgentConfigRequest,
} from '@/types/agent';

// Use centralized HTTP client
const api = httpClient;

/**
 * Error class for tenant agent config API errors
 */
export class TenantAgentConfigError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public details?: unknown
  ) {
    super(message);
    this.name = 'TenantAgentConfigError';
  }
}

/**
 * Tenant Agent Configuration Service implementation
 */
class TenantAgentConfigService implements ITenantAgentConfigService {
  /**
   * Get tenant agent configuration
   *
   * GET /api/v1/agent/config?tenant_id={tenantId}
   *
   * Returns default config if no custom config exists for the tenant.
   *
   * @param tenantId - Tenant ID to get config for
   * @returns Tenant agent configuration
   * @throws TenantAgentConfigError on API errors
   */
  async getConfig(tenantId: string): Promise<TenantAgentConfig> {
    try {
      return await api.get<TenantAgentConfig>('/agent/config', {
        params: { tenant_id: tenantId },
      });
    } catch (error) {
      this._handleError(error, 'Failed to fetch tenant agent configuration');
    }
  }

  /**
   * Update tenant agent configuration (admin only)
   *
   * PUT /api/v1/agent/config?tenant_id={tenantId}
   *
   * Only accessible to tenant administrators.
   * Will return 403 Forbidden for non-admin users.
   *
   * @param tenantId - Tenant ID to update config for
   * @param request - Partial config update (only provided fields are updated)
   * @returns Updated tenant agent configuration
   * @throws TenantAgentConfigError on API errors or permission denied
   */
  async updateConfig(
    tenantId: string,
    request: UpdateTenantAgentConfigRequest
  ): Promise<TenantAgentConfig> {
    try {
      return await api.put<TenantAgentConfig>('/agent/config', request, {
        params: { tenant_id: tenantId },
      });
    } catch (error) {
      this._handleError(error, 'Failed to update tenant agent configuration');
    }
  }

  /**
   * Check if current user can modify tenant config
   *
   * Calls the backend API to determine if the current user
   * has admin privileges for the tenant.
   *
   * @param tenantId - Tenant ID to check permissions for
   * @returns True if user can modify config, false otherwise
   */
  async canModifyConfig(tenantId: string): Promise<boolean> {
    try {
      const response = await api.get<{ can_modify: boolean }>('/agent/config/can-modify', {
        params: { tenant_id: tenantId },
      });
      return response.can_modify;
    } catch (error) {
      // If API fails, assume no permission
      console.warn('Failed to check config modify permission:', error);
      return false;
    }
  }

  /**
   * Handle API errors
   */
  private _handleError(error: unknown, defaultMessage: string): never {
    if (error instanceof ApiError) {
      const statusCode = error.statusCode;
      const detail = error.details;

      // Handle specific error codes
      if (statusCode === 403) {
        throw new TenantAgentConfigError(
          'You do not have permission to modify tenant configuration',
          403,
          detail
        );
      }

      if (statusCode === 404) {
        throw new TenantAgentConfigError('Tenant not found', 404, detail);
      }

      if (statusCode === 422) {
        throw new TenantAgentConfigError('Invalid configuration values', 422, detail);
      }

      // Generic error with detail if available
      throw new TenantAgentConfigError(error.getUserMessage(), statusCode, detail);
    }

    // Non-ApiError errors
    throw new TenantAgentConfigError(defaultMessage, undefined, error);
  }
}

// Export singleton instance
export const agentConfigService = new TenantAgentConfigService();

// Export default
export default agentConfigService;
