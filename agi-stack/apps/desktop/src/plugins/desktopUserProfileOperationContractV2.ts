import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  ProfilePasswordUpdate,
  ProfileRouteObservation,
  ProfileRouteScope,
  ProfileRouteUpdate,
} from '../features/settings-routes/profileRouteClient';
import type { CurrentUser, DesktopRuntimeConfig } from '../types';

export type DesktopUserProfileObservationV2 = ProfileRouteObservation;

export type DesktopUserProfileObserveInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProfileRouteScope;
  signal?: AbortSignal;
}>;

export type DesktopUserProfileUpdateInputV2 = DesktopUserProfileObserveInputV2 &
  Readonly<{ input: ProfileRouteUpdate }>;

export type DesktopUserProfilePasswordInputV2 = DesktopUserProfileObserveInputV2 &
  Readonly<{ input: ProfilePasswordUpdate }>;

export interface DesktopUserProfileAuthorityV2 {
  observe(
    scope: ProfileRouteScope,
    signal?: AbortSignal,
  ): Promise<DesktopUserProfileObservationV2>;
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
}

const CONFIG_KEYS = Object.freeze([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
]);
const UPDATE_KEYS = Object.freeze(['name', 'profile', 'preferred_language']);
const USER_REQUIRED_KEYS = Object.freeze([
  'user_id',
  'email',
  'name',
  'roles',
  'is_active',
  'created_at',
  'profile',
]);
const USER_ALLOWED_KEYS = Object.freeze([
  ...USER_REQUIRED_KEYS,
  'global_roles',
  'is_superuser',
  'preferred_language',
]);
const OBSERVATION_KEYS = Object.freeze([
  'scope',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'itemCount',
  'user',
]);
const CLOUD_ACTIONS = Object.freeze(['view', 'update', 'change-language', 'change-password']);
const LOCAL_ACTIONS = Object.freeze(['view']);

export function prepareDesktopUserProfileObserveV2(
  input: DesktopUserProfileObserveInputV2,
): DesktopUserProfileObserveInputV2 {
  return Object.freeze(prepareCommon(input, ['config', 'scope', 'signal']));
}

export function prepareDesktopUserProfileUpdateV2(
  input: DesktopUserProfileUpdateInputV2,
): DesktopUserProfileUpdateInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'input', 'signal']);
  if (!record(input.input) || !exactOptionalKeys(input.input, UPDATE_KEYS)) throw invalidInput();
  const update: Record<string, unknown> = {};
  if (Object.hasOwn(input.input, 'name')) {
    if (typeof input.input.name !== 'string') throw invalidInput();
    update.name = input.input.name;
  }
  if (Object.hasOwn(input.input, 'profile')) {
    if (!record(input.input.profile)) throw invalidInput();
    update.profile = freezeJsonRecord(input.input.profile);
  }
  if (Object.hasOwn(input.input, 'preferred_language')) {
    if (
      input.input.preferred_language !== 'en-US' &&
      input.input.preferred_language !== 'zh-CN'
    ) {
      throw invalidInput();
    }
    update.preferred_language = input.input.preferred_language;
  }
  return Object.freeze({ ...common, input: Object.freeze(update) }) as DesktopUserProfileUpdateInputV2;
}

export function prepareDesktopUserProfilePasswordV2(
  input: DesktopUserProfilePasswordInputV2,
): DesktopUserProfilePasswordInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'input', 'signal']);
  if (
    !record(input.input) ||
    !exactKeys(input.input, ['oldPassword', 'newPassword']) ||
    typeof input.input.oldPassword !== 'string' ||
    input.input.oldPassword.length === 0 ||
    typeof input.input.newPassword !== 'string' ||
    input.input.newPassword.length === 0
  ) {
    throw invalidInput();
  }
  return Object.freeze({
    ...common,
    input: Object.freeze({
      oldPassword: input.input.oldPassword,
      newPassword: input.input.newPassword,
    }),
  });
}

export function freezeDesktopUserProfileConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !record(config) ||
    !exactKeys(config, CONFIG_KEYS) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  ) {
    throw invalidInput();
  }
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string') {
      throw invalidInput();
    }
  }
  return Object.freeze({ ...config });
}

export function requireDesktopUserProfileObservationV2(
  value: unknown,
  scope: ProfileRouteScope,
): DesktopUserProfileObservationV2 {
  const local = scope.authority === 'local';
  const actions = local ? LOCAL_ACTIONS : CLOUD_ACTIONS;
  if (
    !record(value) ||
    !exactKeys(value, OBSERVATION_KEYS) ||
    !record(value.scope) ||
    !exactKeys(value.scope, ['authority']) ||
    value.scope.authority !== scope.authority ||
    value.authority !== scope.authority ||
    value.availability !== (local ? 'degraded' : 'available') ||
    value.reasonCode !== (local ? 'local_profile_mutation_authority_unavailable' : null) ||
    !sameStrings(value.allowedActions, actions) ||
    value.itemCount !== 1
  ) {
    throw invalidResponse();
  }
  return Object.freeze({
    scope: Object.freeze({ authority: scope.authority }),
    authority: scope.authority,
    availability: local ? 'degraded' : 'available',
    reasonCode: local ? 'local_profile_mutation_authority_unavailable' : null,
    allowedActions: actions,
    itemCount: 1 as const,
    user: requireDesktopUserProfileCurrentUserV2(value.user),
  });
}

export function requireDesktopUserProfileCurrentUserV2(value: unknown): CurrentUser {
  if (
    !record(value) ||
    !exactKeys(value, USER_REQUIRED_KEYS, USER_ALLOWED_KEYS) ||
    typeof value.user_id !== 'string' ||
    typeof value.email !== 'string' ||
    typeof value.name !== 'string' ||
    !stringArray(value.roles) ||
    typeof value.is_active !== 'boolean' ||
    typeof value.created_at !== 'string' ||
    !record(value.profile) ||
    (Object.hasOwn(value, 'global_roles') && !stringArray(value.global_roles)) ||
    (Object.hasOwn(value, 'is_superuser') && typeof value.is_superuser !== 'boolean') ||
    (Object.hasOwn(value, 'preferred_language') &&
      value.preferred_language !== null &&
      value.preferred_language !== 'en-US' &&
      value.preferred_language !== 'zh-CN')
  ) {
    throw invalidResponse();
  }
  return Object.freeze({
    user_id: value.user_id,
    email: value.email,
    name: value.name,
    roles: Object.freeze([...value.roles]) as string[],
    global_roles: Object.freeze(
      Object.hasOwn(value, 'global_roles') ? [...(value.global_roles as string[])] : [],
    ) as string[],
    is_active: value.is_active,
    is_superuser: Object.hasOwn(value, 'is_superuser') ? value.is_superuser === true : false,
    created_at: value.created_at,
    profile: freezeResponseJsonRecord(value.profile),
    preferred_language: Object.hasOwn(value, 'preferred_language')
      ? (value.preferred_language as 'en-US' | 'zh-CN' | null)
      : null,
  });
}

export function requireDesktopUserProfileVoidV2(value: unknown): void {
  if (value !== undefined) throw invalidResponse();
}

function prepareCommon(
  input: DesktopUserProfileObserveInputV2,
  keys: readonly string[],
): DesktopUserProfileObserveInputV2 {
  const required = keys.filter((key) => key !== 'signal');
  if (!record(input) || !exactKeys(input, required, keys)) throw invalidInput();
  const config = freezeDesktopUserProfileConfigV2(input.config);
  if (
    !record(input.scope) ||
    !exactKeys(input.scope, ['authority']) ||
    input.scope.authority !== config.mode ||
    (input.signal !== undefined && !abortSignal(input.signal))
  ) {
    throw invalidInput();
  }
  return {
    config,
    scope: Object.freeze({ authority: input.scope.authority }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
}

function freezeJsonRecord(value: Record<string, unknown>): Readonly<Record<string, unknown>> {
  return freezeJson(value, new WeakSet<object>(), invalidInput) as Readonly<Record<string, unknown>>;
}

function freezeResponseJsonRecord(value: Record<string, unknown>): Record<string, unknown> {
  return freezeJson(value, new WeakSet<object>(), invalidResponse) as Record<string, unknown>;
}

function freezeJson(
  value: unknown,
  ancestors: WeakSet<object>,
  fail: () => RuntimeV2Error,
): unknown {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  ) {
    return value;
  }
  if (typeof value !== 'object' || ancestors.has(value)) throw fail();
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return Object.freeze(value.map((item) => freezeJson(item, ancestors, fail)));
    }
    if (!plainRecord(value)) throw fail();
    const clone: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      if (key === '__proto__' || key === 'prototype' || key === 'constructor') throw fail();
      clone[key] = freezeJson(item, ancestors, fail);
    }
    return Object.freeze(clone);
  } finally {
    ancestors.delete(value);
  }
}

function exactOptionalKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).length > 0 && Object.keys(value).every((key) => allowed.includes(key));
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  allowed: readonly string[] = required,
): boolean {
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => allowed.includes(key))
  );
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function sameStrings(value: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function abortSignal(value: unknown): value is AbortSignal {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as AbortSignal).aborted === 'boolean' &&
    typeof (value as AbortSignal).addEventListener === 'function'
  );
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function plainRecord(value: unknown): value is Record<string, unknown> {
  if (!record(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_user_profile_operation_input_invalid',
    'desktop user profile operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_user_profile_operation_response_invalid',
    'desktop user profile operation response invalid',
  );
}
