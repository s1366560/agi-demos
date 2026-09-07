import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { ProfileRouteClient } from '../features/settings-routes/profileRouteClient';
import type { CurrentUser, DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopUserProfileHttpProjectionV2 } from './desktopUserProfileHttpProjectionV2';
import {
  freezeDesktopUserProfileConfigV2,
  prepareDesktopUserProfileObserveV2,
  prepareDesktopUserProfilePasswordV2,
  prepareDesktopUserProfileUpdateV2,
  requireDesktopUserProfileCurrentUserV2,
  requireDesktopUserProfileObservationV2,
  requireDesktopUserProfileVoidV2,
  type DesktopUserProfileAuthorityV2,
  type DesktopUserProfileObservationV2,
  type DesktopUserProfileObserveInputV2,
  type DesktopUserProfilePasswordInputV2,
  type DesktopUserProfileUpdateInputV2,
} from './desktopUserProfileOperationContractV2';

export const DESKTOP_USER_PROFILE_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/user-profile-authority';
export const DESKTOP_USER_PROFILE_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.user-profile-authority';
export const DESKTOP_USER_PROFILE_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopUserProfileAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: DesktopUserProfileObserveInputV2['scope'],
  ): DesktopUserProfileAuthorityV2;
}

export interface DesktopUserProfileOperationsV2 {
  observeUserProfile(
    input: DesktopUserProfileObserveInputV2,
  ): Promise<DesktopUserProfileObservationV2>;
  updateUserProfile(input: DesktopUserProfileUpdateInputV2): Promise<CurrentUser>;
  changeUserProfilePassword(input: DesktopUserProfilePasswordInputV2): Promise<void>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopUserProfileAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopUserProfileAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopUserProfileAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_user_profile_authority_config_invalid',
      'desktop user profile authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_USER_PROFILE_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopUserProfileHttpProjectionV2(configValue);
      },
    }),
  );
}

export const desktopUserProfileAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_USER_PROFILE_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopUserProfileAuthorityV2,
});

export function createDesktopUserProfileOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopUserProfileOperationsV2 {
  return Object.freeze({
    observeUserProfile(input: DesktopUserProfileObserveInputV2) {
      const prepared = prepareDesktopUserProfileObserveV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopUserProfileObservationV2(
          await authority.observe(prepared.scope, prepared.signal),
          prepared.scope,
        ),
      );
    },
    updateUserProfile(input: DesktopUserProfileUpdateInputV2) {
      const prepared = prepareDesktopUserProfileUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopUserProfileCurrentUserV2(
          await authority.update(prepared.scope, prepared.input, prepared.signal),
        ),
      );
    },
    changeUserProfilePassword(input: DesktopUserProfilePasswordInputV2) {
      const prepared = prepareDesktopUserProfilePasswordV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopUserProfileVoidV2(
          await authority.changePassword(prepared.scope, prepared.input, prepared.signal),
        ),
      );
    },
  });
}

export function createDesktopUserProfileClientV2(
  operations: DesktopUserProfileOperationsV2,
  config: DesktopRuntimeConfig,
): ProfileRouteClient {
  const frozen = freezeDesktopUserProfileConfigV2(config);
  return Object.freeze({
    observe: (scope, signal) =>
      operations.observeUserProfile({
        config: frozen,
        scope,
        ...(signal === undefined ? {} : { signal }),
      }),
    update: (scope, input, signal) =>
      operations.updateUserProfile({
        config: frozen,
        scope,
        input,
        ...(signal === undefined ? {} : { signal }),
      }),
    changePassword: (scope, input, signal) =>
      operations.changeUserProfilePassword({
        config: frozen,
        scope,
        input,
        ...(signal === undefined ? {} : { signal }),
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopUserProfileObserveInputV2,
  operation: (authority: DesktopUserProfileAuthorityV2) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions) {
    throw new DesktopUserProfileAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const admission = await actions.acquireServiceOperationLease<DesktopUserProfileAuthorityServiceV2>(
    {
      service: DESKTOP_USER_PROFILE_AUTHORITY_SERVICE_V2,
      version: DESKTOP_USER_PROFILE_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'root' }),
    },
  );
  if (admission.status === 'rejected') {
    throw new DesktopUserProfileAuthorityUnavailableErrorV2(admission);
  }
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      assertActive(active);
      const service = requireService(candidate);
      const authority = wrapAuthority(service.bindOperation(prepared.config, prepared.scope), () => active);
      const result = await operation(authority);
      assertActive(active);
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}

function requireService(value: unknown): DesktopUserProfileAuthorityServiceV2 {
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopUserProfileAuthorityServiceV2;
}

function wrapAuthority(raw: unknown, active: () => boolean): DesktopUserProfileAuthorityV2 {
  const methods = ['observe', 'update', 'changePassword'] as const;
  if (
    !record(raw) ||
    Object.keys(raw).length !== methods.length ||
    methods.some((method) => typeof raw[method] !== 'function')
  ) {
    throw invalidService();
  }
  const source = raw as unknown as DesktopUserProfileAuthorityV2;
  return Object.freeze({
    observe: (scope: DesktopUserProfileObserveInputV2['scope'], signal?: AbortSignal) =>
      invoke(active, source.observe, [scope, signal]),
    update: (
      scope: DesktopUserProfileObserveInputV2['scope'],
      input: DesktopUserProfileUpdateInputV2['input'],
      signal?: AbortSignal,
    ) => invoke(active, source.update, [scope, input, signal]),
    changePassword: (
      scope: DesktopUserProfileObserveInputV2['scope'],
      input: DesktopUserProfilePasswordInputV2['input'],
      signal?: AbortSignal,
    ) => invoke(active, source.changePassword, [scope, input, signal]),
  });
}

async function invoke<TArgs extends readonly unknown[], TResult>(
  active: () => boolean,
  operation: (...args: TArgs) => TResult | Promise<TResult>,
  args: TArgs,
): Promise<TResult> {
  assertActive(active());
  const result = await operation(...args);
  assertActive(active());
  return result;
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_user_profile_operation_released',
      'desktop user profile operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_user_profile_service_invalid',
    'desktop user profile authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_USER_PROFILE_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_user_profile_authority_catalog_missing',
      'desktop user profile authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
