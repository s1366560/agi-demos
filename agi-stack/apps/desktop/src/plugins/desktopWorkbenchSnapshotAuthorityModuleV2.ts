import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { DesktopCapabilitySnapshot } from '../features/runtime/capabilitySnapshot';
import { createDesktopWorkbenchSnapshotDependenciesV2 } from '../features/runtime/desktopWorkbenchSnapshotDependenciesV2';
import type { DesktopWorkbenchCapabilityClient } from '../features/runtime/workbenchCapabilityClient';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';

export const DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workbench-snapshot-authority';
export const DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workbench-snapshot-authority';
export const DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopWorkbenchSnapshotAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    actions: DesktopRendererGenerationActionsV2,
  ) => DesktopWorkbenchCapabilityClient;
}

export interface DesktopWorkbenchSnapshotOperationsV2 {
  readonly loadSnapshot: (
    input: Readonly<{
      config: DesktopRuntimeConfig;
      signal: AbortSignal;
    }>,
  ) => Promise<DesktopCapabilitySnapshot>;
}

export function applyDesktopWorkbenchSnapshotAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'same-generation-snapshot') {
    throw new RuntimeV2Error(
      'desktop_workbench_snapshot_config_invalid',
      'workbench snapshot requires the same-generation-snapshot strategy',
    );
  }
  const service = Object.freeze<DesktopWorkbenchSnapshotAuthorityServiceV2>({
    bindOperation: (operationConfig, actions) =>
      createDesktopWorkbenchSnapshotDependenciesV2(operationConfig, () => actions),
  });
  context.provide(DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkbenchSnapshotAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopWorkbenchSnapshotAuthorityV2,
});

export function createDesktopWorkbenchSnapshotOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkbenchSnapshotOperationsV2 {
  return Object.freeze<DesktopWorkbenchSnapshotOperationsV2>({
    async loadSnapshot(input) {
      const config = freezeConfigV2(input.config);
      const signal = input.signal;
      if (!(signal instanceof AbortSignal)) throw snapshotErrorV2('input_invalid');
      signal.throwIfAborted();
      const actions = resolveActions();
      if (actions === null) throw snapshotErrorV2('generation_actions_unavailable');
      const admission =
        await actions.acquireServiceOperationLease<DesktopWorkbenchSnapshotAuthorityServiceV2>({
          service: DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_SERVICE_V2,
          version: DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_VERSION_V2,
          scope: Object.freeze({ kind: 'root' }),
        });
      if (admission.status === 'rejected') {
        throw new RuntimeV2Error(
          admission.reasonCode,
          admission.runtimeCode ?? admission.reasonCode,
        );
      }
      let active = true;
      let consumed = false;
      let failed = false;
      try {
        const acquireChild = admission.acquireChildServiceLease;
        if (acquireChild === undefined) throw snapshotErrorV2('parent_lease_required');
        const childActions = Object.freeze<DesktopRendererGenerationActionsV2>({
          acquireOperationLease: () => {
            throw snapshotErrorV2('service_lease_required');
          },
          acquireServiceOperationLease: (request) => {
            if (!active) throw snapshotErrorV2('operation_released');
            signal.throwIfAborted();
            return acquireChild(request);
          },
        });
        return await admission.useService(async (service) => {
          if (!active || consumed) throw snapshotErrorV2('operation_released');
          consumed = true;
          signal.throwIfAborted();
          const snapshot = await service.bindOperation(config, childActions).loadSnapshot(signal);
          signal.throwIfAborted();
          return snapshot;
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
    },
  });
}

function freezeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (typeof config !== 'object' || config === null) throw snapshotErrorV2('input_invalid');
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local')
  )
    throw snapshotErrorV2('input_invalid');
  return Object.freeze(copy);
}

function snapshotErrorV2(suffix: string): RuntimeV2Error {
  return new RuntimeV2Error(
    `desktop_workbench_snapshot_${suffix}`,
    `workbench snapshot: ${suffix}`,
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) throw snapshotErrorV2('catalog_missing');
  return entry.contract_digest;
}
