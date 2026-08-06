import type { CurrentUser, DesktopRuntimeConfig } from '../../types';
import {
  isNativeRouteRecord,
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
  unavailableNativeRouteAction,
} from './nativeRouteHttpClient';

export type ProfileRouteScope = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
}>;

export type ProfileRouteUpdate = Readonly<{
  name?: string;
  profile?: Readonly<Record<string, unknown>>;
  preferred_language?: 'en-US' | 'zh-CN';
}>;

export type ProfilePasswordUpdate = Readonly<{
  oldPassword: string;
  newPassword: string;
}>;

export type ProfileRouteObservation = Readonly<{
  scope: ProfileRouteScope;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  allowedActions: readonly string[];
  itemCount: 1;
  user: CurrentUser;
}>;

export type ProfileRouteClient = Readonly<{
  observe(scope: ProfileRouteScope, signal?: AbortSignal): Promise<ProfileRouteObservation>;
  update(
    scope: ProfileRouteScope,
    input: ProfileRouteUpdate,
    signal?: AbortSignal,
  ): Promise<CurrentUser>;
  changePassword(
    scope: ProfileRouteScope,
    input: ProfilePasswordUpdate,
    signal?: AbortSignal,
  ): Promise<void>;
}>;

const CLOUD_ACTIONS = Object.freeze(['view', 'update', 'change-language', 'change-password']);
const LOCAL_ACTIONS = Object.freeze(['view']);

export function createProfileRouteClient(config: DesktopRuntimeConfig): ProfileRouteClient {
  const runtime = Object.freeze({ ...config });
  return Object.freeze({
    async observe(scope, signal) {
      const current = requireScope(runtime, scope);
      const user = parseUser(await requestNativeRouteJson(runtime, '/api/v1/auth/me', { signal }));
      const local = current.authority === 'local';
      return Object.freeze({
        scope: current,
        authority: current.authority,
        availability: local ? 'degraded' : 'available',
        reasonCode: local ? 'local_profile_mutation_authority_unavailable' : null,
        allowedActions: local ? LOCAL_ACTIONS : CLOUD_ACTIONS,
        itemCount: 1 as const,
        user,
      });
    },
    async update(scope, input, signal) {
      const current = requireScope(runtime, scope);
      if (current.authority === 'local') {
        unavailableNativeRouteAction('local_profile_mutation_authority_unavailable');
      }
      return parseUser(
        await requestNativeRouteJson(runtime, '/api/v1/users/me', {
          method: 'PUT',
          body: input,
          signal,
        }),
      );
    },
    async changePassword(scope, input, signal) {
      const current = requireScope(runtime, scope);
      if (current.authority === 'local') {
        unavailableNativeRouteAction('local_profile_mutation_authority_unavailable');
      }
      if (!input.oldPassword || !input.newPassword) {
        throw new NativeRouteClientError('user_profile_password_input_invalid', 422);
      }
      await requestNativeRouteJson(runtime, '/api/v1/auth/force-change-password', {
        method: 'POST',
        body: {
          old_password: input.oldPassword,
          new_password: input.newPassword,
        },
        signal,
      });
    },
  });
}

function requireScope(config: DesktopRuntimeConfig, scope: ProfileRouteScope): ProfileRouteScope {
  requireRuntimeAuthority(config, scope.authority, 'user_profile_runtime_scope_mismatch');
  return Object.freeze({ authority: scope.authority });
}

function parseUser(payload: unknown): CurrentUser {
  if (
    !isNativeRouteRecord(payload) ||
    typeof payload.user_id !== 'string' ||
    typeof payload.email !== 'string' ||
    typeof payload.name !== 'string' ||
    !Array.isArray(payload.roles) ||
    payload.roles.some((role) => typeof role !== 'string') ||
    typeof payload.is_active !== 'boolean' ||
    typeof payload.created_at !== 'string' ||
    !isNativeRouteRecord(payload.profile)
  ) {
    throw new NativeRouteClientError('user_profile_contract_invalid', 502, payload);
  }
  return Object.freeze({
    user_id: payload.user_id,
    email: payload.email,
    name: payload.name,
    roles: Object.freeze([...payload.roles]) as string[],
    global_roles: Array.isArray(payload.global_roles)
      ? (Object.freeze(payload.global_roles.filter((role) => typeof role === 'string')) as string[])
      : [],
    is_active: payload.is_active,
    is_superuser: payload.is_superuser === true,
    created_at: payload.created_at,
    profile: Object.freeze({ ...payload.profile }),
    preferred_language:
      payload.preferred_language === 'en-US' || payload.preferred_language === 'zh-CN'
        ? payload.preferred_language
        : null,
  });
}
