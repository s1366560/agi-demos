import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopActivityAuthorityClient } from '../features/agent-authority/agentAuthorityTypes';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopProjectActivityReadStateHttpProjectionV2 } from './desktopProjectActivityReadStateHttpProjectionV2';
import {
  ACTIVITY_READ_STATE_METHODS_V2,
  freezeActivityReadStateConfigV2,
  prepareActivityReadStateInputV2,
  activityReadStateErrorV2,
  activityReadStateRecordV2,
  type ActivityReadStateInputV2,
  type ActivityReadStateMethodV2,
  type ActivityReadStateResultsV2,
  requireActivityReadStateResultV2,
  type DesktopProjectActivityReadStateAuthorityV2,
} from './desktopProjectActivityReadStateOperationContractV2';

export const DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-activity-read-state-authority';
export const DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-activity-read-state-authority';
export const DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopProjectActivityReadStateAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopProjectActivityReadStateAuthorityV2;
}
export type DesktopProjectActivityReadStateOperationsV2 = {
  readonly [K in ActivityReadStateMethodV2]: (
    input: ActivityReadStateInputV2,
  ) => Promise<ActivityReadStateResultsV2[K]>;
};
export type DesktopProjectActivityReadStateClientV2 = DesktopActivityAuthorityClient;
export function applyDesktopProjectActivityReadStateAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_project_activity_read_state_authority_config_invalid',
      'invalid Activity read state authority config',
    );
  context.provide(
    DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopProjectActivityReadStateHttpProjectionV2 }),
  );
}
export const desktopProjectActivityReadStateAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopProjectActivityReadStateAuthorityV2,
  });
export function createDesktopProjectActivityReadStateOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectActivityReadStateOperationsV2 {
  const run = async <K extends ActivityReadStateMethodV2>(
    method: K,
    input: ActivityReadStateInputV2,
  ): Promise<ActivityReadStateResultsV2[K]> => {
    const p = prepareActivityReadStateInputV2(method, input);
    const actions = resolve();
    if (!actions)
      throw activityReadStateErrorV2('desktop_renderer_generation_actions_unavailable', 503);
    const lease =
      await actions.acquireServiceOperationLease<DesktopProjectActivityReadStateAuthorityServiceV2>(
        {
          service: DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_SERVICE_V2,
          version: DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_VERSION_V2,
          scope: Object.freeze({
            kind: 'project',
            tenant_id: p.scope.tenantId,
            project_id: p.scope.projectId,
          }),
        },
      );
    if (lease.status !== 'accepted') throw activityReadStateErrorV2(lease.reasonCode, 503);
    let active = true;
    let consumed = false;
    let failed = false;
    const check = () => {
      if (!active)
        throw new RuntimeV2Error(
          'project_activity_read_state_operation_released',
          'Activity read state operation released',
        );
      if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    };
    try {
      return await lease.useService(async (candidate) => {
        check();
        if (consumed)
          throw activityReadStateErrorV2('project_activity_read_state_callback_consumed', 409);
        consumed = true;
        if (
          !activityReadStateRecordV2(candidate) ||
          Object.keys(candidate).length !== 1 ||
          typeof candidate.bindOperation !== 'function'
        )
          throw activityReadStateErrorV2('project_activity_read_state_service_invalid', 502);
        const authority = candidate.bindOperation(p.config);
        if (
          !activityReadStateRecordV2(authority) ||
          Object.keys(authority).length !== 1 ||
          typeof authority.execute !== 'function'
        )
          throw activityReadStateErrorV2('project_activity_read_state_service_invalid', 502);
        check();
        const raw = await authority.execute(method, p);
        check();
        return requireActivityReadStateResultV2(method, raw, p);
      });
    } catch (error) {
      failed = true;
      throw error;
    } finally {
      active = false;
      try {
        await lease.release();
      } catch (error) {
        if (!failed) throw error;
      }
    }
  };
  return createActivityReadStateOperationsTableV2(run);
}
export function createActivityReadStateOperationsTableV2(
  run: <K extends ActivityReadStateMethodV2>(
    method: K,
    input: ActivityReadStateInputV2,
  ) => Promise<ActivityReadStateResultsV2[K]>,
): DesktopProjectActivityReadStateOperationsV2 {
  return Object.freeze(
    Object.fromEntries(
      ACTIVITY_READ_STATE_METHODS_V2.map((method) => [
        method,
        (input: ActivityReadStateInputV2) => run(method, input),
      ]),
    ),
  ) as DesktopProjectActivityReadStateOperationsV2;
}
export function createDesktopProjectActivityReadStateClientV2(
  operations: DesktopProjectActivityReadStateOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopProjectActivityReadStateClientV2 {
  const runtime = freezeActivityReadStateConfigV2(config);
  return Object.freeze({
    getActivityReadState: (scope, options) =>
      operations.getActivityReadState({ config: runtime, scope, signal: options?.signal }),
    putActivityReadState: (scope, request, options) =>
      operations.putActivityReadState({ config: runtime, scope, request, signal: options?.signal }),
    flushPendingActivityReadState: (scope, options) =>
      operations.flushPendingActivityReadState({ config: runtime, scope, signal: options?.signal }),
  } satisfies DesktopActivityAuthorityClient);
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_project_activity_read_state_authority_catalog_missing',
      'Activity read state authority absent from catalog',
    );
  return entry.contract_digest;
}
