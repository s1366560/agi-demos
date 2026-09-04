import type { ProfileRouteScope, ProfileRouteUpdate } from '../features/settings-routes/profileRouteClient';
import {
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
  unavailableNativeRouteAction,
} from '../features/settings-routes/nativeRouteHttpClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  requireDesktopUserProfileCurrentUserV2,
  type DesktopUserProfileAuthorityV2,
  type DesktopUserProfileObservationV2,
} from './desktopUserProfileOperationContractV2';

export const DESKTOP_USER_PROFILE_LOCAL_MUTATION_REASON_V2 =
  'local_profile_mutation_authority_unavailable';

const CLOUD_ACTIONS = Object.freeze(['view', 'update', 'change-language', 'change-password']);
const LOCAL_ACTIONS = Object.freeze(['view']);

export function createDesktopUserProfileHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopUserProfileAuthorityV2 {
  const runtime = Object.freeze({ ...config });
  const authority: DesktopUserProfileAuthorityV2 = {
    async observe(scope, signal): Promise<DesktopUserProfileObservationV2> {
      const current = requireScope(runtime, scope);
      const user = requireDesktopUserProfileCurrentUserV2(
        await requestNativeRouteJson(runtime, '/api/v1/auth/me', { signal }),
      );
      const local = current.authority === 'local';
      return Object.freeze({
        scope: current,
        authority: current.authority,
        availability: local ? 'degraded' : 'available',
        reasonCode: local ? DESKTOP_USER_PROFILE_LOCAL_MUTATION_REASON_V2 : null,
        allowedActions: local ? LOCAL_ACTIONS : CLOUD_ACTIONS,
        itemCount: 1 as const,
        user,
      });
    },
    async update(scope, input, signal) {
      const current = requireScope(runtime, scope);
      rejectLocalMutation(current);
      return requireDesktopUserProfileCurrentUserV2(
        await requestNativeRouteJson(runtime, '/api/v1/users/me', {
          method: 'PUT',
          body: input satisfies ProfileRouteUpdate,
          signal,
        }),
      );
    },
    async changePassword(scope, input, signal) {
      const current = requireScope(runtime, scope);
      rejectLocalMutation(current);
      const response = await requestNativeRouteJson(
        runtime,
        '/api/v1/auth/force-change-password',
        {
          method: 'POST',
          body: {
            old_password: input.oldPassword,
            new_password: input.newPassword,
          } satisfies Readonly<{ old_password: string; new_password: string }>,
          signal,
        },
      );
      if (
        !record(response) ||
        Object.keys(response).length !== 2 ||
        response.success !== true ||
        typeof response.message !== 'string'
      ) {
        throw new NativeRouteClientError('user_profile_password_contract_invalid', 502, null);
      }
    },
  };
  return Object.freeze(authority);
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: ProfileRouteScope,
): ProfileRouteScope {
  requireRuntimeAuthority(config, scope.authority, 'user_profile_runtime_scope_mismatch');
  return Object.freeze({ authority: scope.authority });
}

function rejectLocalMutation(scope: ProfileRouteScope): void {
  if (scope.authority === 'local') {
    unavailableNativeRouteAction(DESKTOP_USER_PROFILE_LOCAL_MUTATION_REASON_V2);
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
