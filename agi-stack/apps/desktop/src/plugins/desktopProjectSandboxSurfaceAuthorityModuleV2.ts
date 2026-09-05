import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopProjectSandboxSurfaceHttpProjectionV2 } from './desktopProjectSandboxSurfaceHttpProjectionV2';
import {
  SANDBOX_SURFACE_METHODS_V2,
  freezeSandboxSurfaceConfigV2,
  prepareSandboxSurfaceInputV2,
  sandboxSurfaceErrorV2,
  sandboxSurfaceRecordV2,
  type SandboxSurfaceArgumentsV2,
  type SandboxSurfaceInputV2,
  type SandboxSurfaceMethodV2,
  type SandboxSurfaceResultsV2,
  type DesktopProjectSandboxSurfaceAuthorityV2,
} from './desktopProjectSandboxSurfaceOperationContractV2';
import { requireSandboxSurfaceResultV2 } from './desktopProjectSandboxSurfaceResponseContractV2';
export const DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-sandbox-surface-authority';
export const DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-sandbox-surface-authority';
export const DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopProjectSandboxSurfaceAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopProjectSandboxSurfaceAuthorityV2;
}
export type DesktopProjectSandboxSurfaceOperationsV2 = {
  readonly [K in SandboxSurfaceMethodV2]: (
    input: SandboxSurfaceInputV2<K>,
  ) => Promise<SandboxSurfaceResultsV2[K]>;
};
export type DesktopProjectSandboxSurfaceClientV2 = {
  readonly [K in SandboxSurfaceMethodV2]: (
    ...args: [...SandboxSurfaceArgumentsV2[K], signal?: AbortSignal]
  ) => Promise<SandboxSurfaceResultsV2[K]>;
};
export function applyDesktopProjectSandboxSurfaceAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_project_sandbox_surface_authority_config_invalid',
      'invalid Sandbox surface authority config',
    );
  context.provide(
    DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopProjectSandboxSurfaceHttpProjectionV2 }),
  );
}
export const desktopProjectSandboxSurfaceAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopProjectSandboxSurfaceAuthorityV2,
});
export function createDesktopProjectSandboxSurfaceOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectSandboxSurfaceOperationsV2 {
  const run = async <K extends SandboxSurfaceMethodV2>(
    method: K,
    input: SandboxSurfaceInputV2<K>,
  ): Promise<SandboxSurfaceResultsV2[K]> => {
    const p = prepareSandboxSurfaceInputV2(method, input);
    const actions = resolve();
    if (!actions)
      throw sandboxSurfaceErrorV2('desktop_renderer_generation_actions_unavailable', 503);
    const lease =
      await actions.acquireServiceOperationLease<DesktopProjectSandboxSurfaceAuthorityServiceV2>({
        service: DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_SERVICE_V2,
        version: DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: 'project',
          tenant_id: p.scope.tenantId,
          project_id: p.scope.projectId,
        }),
      });
    if (lease.status !== 'accepted') throw sandboxSurfaceErrorV2(lease.reasonCode, 503);
    let active = true;
    let failed = false;
    let retained = false;
    let consumed = false;
    let releasePromise: Promise<void> | undefined;
    const onAbort = () => {
      void release().catch(() => undefined);
    };
    const release = (): Promise<void> => {
      if (releasePromise) return releasePromise;
      active = false;
      p.signal?.removeEventListener('abort', onAbort);
      releasePromise = Promise.resolve().then(() => lease.release());
      return releasePromise;
    };
    const check = () => {
      if (!active)
        throw new RuntimeV2Error(
          'project_sandbox_surface_operation_released',
          'Sandbox surface operation released',
        );
      if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    };
    try {
      return await lease.useService(async (candidate) => {
        check();
        if (consumed) throw sandboxSurfaceErrorV2('project_sandbox_surface_callback_consumed', 409);
        consumed = true;
        if (
          !sandboxSurfaceRecordV2(candidate) ||
          Object.keys(candidate).length !== 1 ||
          typeof candidate.bindOperation !== 'function'
        )
          throw sandboxSurfaceErrorV2('project_sandbox_surface_service_invalid', 502);
        const authority = candidate.bindOperation(p.config);
        if (
          !sandboxSurfaceRecordV2(authority) ||
          Object.keys(authority).length !== 1 ||
          typeof authority.execute !== 'function'
        )
          throw sandboxSurfaceErrorV2('project_sandbox_surface_service_invalid', 502);
        check();
        const raw = await authority.execute(method, p);
        check();
        const result = requireSandboxSurfaceResultV2(method, raw, p);
        if (method === 'openRemoteDesktop' && 'status' in result && result.status === 'ready') {
          p.signal?.addEventListener('abort', onAbort, { once: true });
          if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
          retained = true;
          return Object.freeze({
            status: 'ready',
            value: Object.freeze({ ...result.value, release }),
          }) as SandboxSurfaceResultsV2[K];
        }
        return result;
      });
    } catch (error) {
      failed = true;
      throw error;
    } finally {
      if (!retained) {
        try {
          await release();
        } catch (error) {
          if (!failed) throw error;
        }
      }
    }
  };
  return createSandboxSurfaceOperationsTableV2(run);
}
export function createSandboxSurfaceOperationsTableV2(
  run: <K extends SandboxSurfaceMethodV2>(
    method: K,
    input: SandboxSurfaceInputV2<K>,
  ) => Promise<SandboxSurfaceResultsV2[K]>,
): DesktopProjectSandboxSurfaceOperationsV2 {
  return Object.freeze(
    Object.fromEntries(
      SANDBOX_SURFACE_METHODS_V2.map((method) => [
        method,
        (input: SandboxSurfaceInputV2) => run(method, input),
      ]),
    ),
  ) as DesktopProjectSandboxSurfaceOperationsV2;
}
export function createDesktopProjectSandboxSurfaceClientV2(
  operations: DesktopProjectSandboxSurfaceOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopProjectSandboxSurfaceClientV2 {
  const runtime = freezeSandboxSurfaceConfigV2(config);
  const scope = Object.freeze({
    authority: runtime.mode,
    tenantId: runtime.tenantId,
    projectId: runtime.projectId,
  });
  const call = <K extends SandboxSurfaceMethodV2>(
    method: K,
    args: SandboxSurfaceArgumentsV2[K],
    signal?: AbortSignal,
  ) => operations[method]({ config: runtime, scope, args, signal });
  const client: DesktopProjectSandboxSurfaceClientV2 = {
    loadCapabilities: (signal) => call('loadCapabilities', [], signal),
    openRemoteDesktop: (caps, request, signal) =>
      call('openRemoteDesktop', [caps, request], signal),
    listFiles: (caps, request, signal) => call('listFiles', [caps, request], signal),
    readFile: (caps, request, signal) => call('readFile', [caps, request], signal),
    downloadFile: (caps, request, signal) => call('downloadFile', [caps, request], signal),
  };
  return Object.freeze(client);
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_PROJECT_SANDBOX_SURFACE_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_project_sandbox_surface_authority_catalog_missing',
      'Sandbox surface authority absent from catalog',
    );
  return entry.contract_digest;
}
