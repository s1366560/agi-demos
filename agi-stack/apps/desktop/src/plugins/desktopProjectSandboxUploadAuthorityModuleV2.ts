import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { AgentInputFileMetadata, DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopProjectSandboxUploadHttpProjectionV2 } from './desktopProjectSandboxUploadHttpProjectionV2';
import {
  checkSandboxUploadAbortV2,
  freezeSandboxUploadConfigV2,
  prepareSandboxUploadInputV2,
  sandboxUploadErrorV2,
  sandboxUploadRecordV2,
  type DesktopProjectSandboxUploadAuthorityV2,
  type DesktopSandboxUploadFileV2,
  type ProjectSandboxUploadInputV2,
} from './desktopProjectSandboxUploadOperationContractV2';
import { requireSandboxUploadResultV2 } from './desktopProjectSandboxUploadResponseContractV2';
export const DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-sandbox-upload-authority';
export const DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-sandbox-upload-authority';
export const DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopProjectSandboxUploadAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopProjectSandboxUploadAuthorityV2;
}
export interface DesktopProjectSandboxUploadOperationsV2 {
  uploadSandboxFile(input: ProjectSandboxUploadInputV2): Promise<AgentInputFileMetadata>;
}
export interface DesktopProjectSandboxUploadClientV2 {
  uploadSandboxFile(
    file: DesktopSandboxUploadFileV2,
    signal?: AbortSignal,
  ): Promise<AgentInputFileMetadata>;
}
export function applyDesktopProjectSandboxUploadAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_project_sandbox_upload_authority_config_invalid',
      'Invalid sandbox upload authority config',
    );
  context.provide(
    DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopProjectSandboxUploadHttpProjectionV2 }),
  );
}
export const desktopProjectSandboxUploadAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopProjectSandboxUploadAuthorityV2,
});
export function createDesktopProjectSandboxUploadOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectSandboxUploadOperationsV2 {
  return Object.freeze({
    async uploadSandboxFile(input: ProjectSandboxUploadInputV2) {
      const p = prepareSandboxUploadInputV2(input);
      const actions = resolve();
      if (!actions)
        throw sandboxUploadErrorV2('desktop_renderer_generation_actions_unavailable', 503);
      const lease =
        await actions.acquireServiceOperationLease<DesktopProjectSandboxUploadAuthorityServiceV2>({
          service: DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_SERVICE_V2,
          version: DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_VERSION_V2,
          scope: Object.freeze({
            kind: 'project',
            tenant_id: p.scope.tenantId,
            project_id: p.scope.projectId,
          }),
        });
      if (lease.status !== 'accepted') throw sandboxUploadErrorV2(lease.reasonCode, 503);
      let active = true;
      let failed = false;
      const check = () => {
        if (!active)
          throw new RuntimeV2Error(
            'project_sandbox_upload_operation_released',
            'Sandbox upload operation released',
          );
        checkSandboxUploadAbortV2(p.signal);
      };
      try {
        return await lease.useService(async (candidate) => {
          check();
          if (
            !sandboxUploadRecordV2(candidate) ||
            Object.keys(candidate).length !== 1 ||
            typeof candidate.bindOperation !== 'function'
          )
            throw sandboxUploadErrorV2('project_sandbox_upload_service_invalid', 502);
          const authority = candidate.bindOperation(p.config);
          if (
            !sandboxUploadRecordV2(authority) ||
            Object.keys(authority).length !== 1 ||
            typeof authority.uploadSandboxFile !== 'function'
          )
            throw sandboxUploadErrorV2('project_sandbox_upload_service_invalid', 502);
          check();
          const raw = await authority.uploadSandboxFile(p);
          check();
          return requireSandboxUploadResultV2(raw, p);
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
    },
  });
}
export function createDesktopProjectSandboxUploadClientV2(
  operations: DesktopProjectSandboxUploadOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopProjectSandboxUploadClientV2 {
  const runtime = freezeSandboxUploadConfigV2(config);
  const scope = Object.freeze({
    authority: runtime.mode,
    tenantId: runtime.tenantId,
    projectId: runtime.projectId,
  });
  return Object.freeze({
    uploadSandboxFile: (file: DesktopSandboxUploadFileV2, signal?: AbortSignal) =>
      operations.uploadSandboxFile({ config: runtime, scope, file, signal }),
  });
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_PROJECT_SANDBOX_UPLOAD_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_project_sandbox_upload_authority_catalog_missing',
      'Sandbox upload authority absent from catalog',
    );
  return entry.contract_digest;
}
