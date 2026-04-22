/**
 * deviceAuthService - Device-code OAuth flow for CLI login.
 *
 * Mirrors the 3 backend endpoints in src/.../routers/auth.py:
 *   POST /auth/device/code       (unauth) — start flow
 *   POST /auth/device/approve    (auth)   — user approves a user_code
 *   POST /auth/device/token      (unauth) — CLI polls for the key
 *
 * The frontend only needs `approve` (the CLI handles the others).
 */
import { httpClient } from './client/httpClient';

export interface DeviceApproveResponse {
  status: 'approved';
  user_code: string;
}

export const deviceAuthService = {
  /**
   * Approve a pending CLI login by its user_code.
   *
   * Requires the caller to be authenticated (uses the current session's
   * API key). The backend mints a new `ms_sk_` key bound to the current
   * user with 30-day expiry and hands it to the waiting CLI.
   */
  approve: async (userCode: string): Promise<DeviceApproveResponse> => {
    return await httpClient.post<DeviceApproveResponse>(
      '/auth/device/approve',
      { user_code: userCode.trim().toUpperCase() }
    );
  },
};
