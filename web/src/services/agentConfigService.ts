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

import axios, { type AxiosError } from 'axios';
import type {
  TenantAgentConfig,
  TenantAgentConfigService as ITenantAgentConfigService,
  UpdateTenantAgentConfigRequest,
} from '@/types/agent';

// Base API URL from environment
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

// Create axios instance for agent config API with custom baseURL
// Note: This service uses a custom baseURL (/api/v1/agent) so it creates
// its own instance. The centralized client is still used for standard endpoints.
const agentConfigApi = axios.create({
  baseURL: `${API_BASE_URL}/agent`,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth token interceptor
agentConfigApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

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
      const response = await agentConfigApi.get<TenantAgentConfig>('/config', {
        params: { tenant_id: tenantId },
      });
      return response.data;
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
      const response = await agentConfigApi.put<TenantAgentConfig>(
        '/config',
        request,
        {
          params: { tenant_id: tenantId },
        }
      );
      return response.data;
    } catch (error) {
      this._handleError(error, 'Failed to update tenant agent configuration');
    }
  }

  /**
   * Check if current user can modify tenant config
   *
   * This method attempts to determine if the current user
   * has admin privileges for the tenant.
   *
   * Currently a placeholder - in production this would check
   * user roles/permissions from the auth context.
   *
   * @param _tenantId - Tenant ID to check permissions for
   * @returns True if user can modify config, false otherwise
   */
  async canModifyConfig(_tenantId: string): Promise<boolean> {
    // TODO: Implement proper permission check
    // Options:
    // 1. Add a dedicated endpoint: GET /api/v1/agent/config/can-modify?tenant_id={id}
    // 2. Check user roles from auth context/tenant store
    // 3. Try a minimal update and catch 403 (not recommended)

    // For now, return true and let the actual update fail with 403
    // The UI should handle the 403 gracefully
    return true;
  }

  /**
   * Handle API errors
   */
  private _handleError(error: unknown, defaultMessage: string): never {
    if (axios.isAxiosError(error)) {
      const axiosError = error as AxiosError<{ detail?: string }>;
      const statusCode = axiosError.response?.status;
      const detail = axiosError.response?.data?.detail;

      // Handle specific error codes
      if (statusCode === 403) {
        throw new TenantAgentConfigError(
          'You do not have permission to modify tenant configuration',
          403,
          detail
        );
      }

      if (statusCode === 404) {
        throw new TenantAgentConfigError(
          'Tenant not found',
          404,
          detail
        );
      }

      if (statusCode === 422) {
        throw new TenantAgentConfigError(
          'Invalid configuration values',
          422,
          detail
        );
      }

      // Generic error with detail if available
      throw new TenantAgentConfigError(
        detail || defaultMessage,
        statusCode,
        axiosError.response?.data
      );
    }

    // Non-Axios errors
    throw new TenantAgentConfigError(defaultMessage, undefined, error);
  }
}

// Export singleton instance
export const agentConfigService = new TenantAgentConfigService();

// Export default
export default agentConfigService;
