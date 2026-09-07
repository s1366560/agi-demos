import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type {
  DesktopRuntimeConfig,
  ManagedSkillImportInput,
  ManagedSkillZipImportInput,
  ManagedSkillLifecycle,
  ManagedSkillPackage,
  ManagedSkillVersionList,
  ManagedSkillVersionDetail,
  ManagedSkill,
} from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopTenantSkillPackagesHttpProjectionV2 } from './desktopTenantSkillPackagesHttpProjectionV2';
import { requireDesktopTenantSkillDefinitionV2 } from './desktopTenantSkillDefinitionsOperationContractV2';
import {
  prepareSkillPackageImportV2,
  prepareSkillPackageZipV2,
  prepareSkillPackageItemV2,
  prepareSkillPackageVersionV2,
  requireSkillLifecycleV2,
  requireSkillPackageV2,
  requireSkillVersionsV2,
  requireSkillVersionV2,
  type DesktopTenantSkillPackagesAuthorityV2,
  type SkillPackageImportInputV2,
  type SkillPackageZipInputV2,
  type SkillPackageItemInputV2,
  type SkillPackageVersionInputV2,
} from './desktopTenantSkillPackagesOperationContractV2';
import {
  freezeSkillConfigV2,
  runSkillOperationV2,
  type SkillInputV2,
} from './desktopTenantSkillOperationSupportV2';
export const DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-skill-packages-authority';
export const DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-skill-packages-authority';
export const DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopTenantSkillPackagesAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopTenantSkillPackagesAuthorityV2;
}
export interface DesktopTenantSkillPackagesOperationsV2 {
  importTenantSkillPackage(input: SkillPackageImportInputV2): Promise<ManagedSkillLifecycle>;
  importTenantSkillZip(input: SkillPackageZipInputV2): Promise<ManagedSkillLifecycle>;
  listTenantSkillVersions(input: SkillPackageItemInputV2): Promise<ManagedSkillVersionList>;
  rollbackTenantSkill(input: SkillPackageVersionInputV2): Promise<ManagedSkill>;
  exportTenantSkillPackage(input: SkillPackageItemInputV2): Promise<ManagedSkillPackage>;
  getTenantSkillVersion(input: SkillPackageVersionInputV2): Promise<ManagedSkillVersionDetail>;
}
export interface DesktopTenantSkillPackagesClientV2 {
  importManagedSkillPackage(
    input: ManagedSkillImportInput,
    signal?: AbortSignal,
  ): Promise<ManagedSkillLifecycle>;
  importManagedSkillZip(
    archive: File,
    input?: ManagedSkillZipImportInput,
    signal?: AbortSignal,
  ): Promise<ManagedSkillLifecycle>;
  listManagedSkillVersions(skillId: string, signal?: AbortSignal): Promise<ManagedSkillVersionList>;
  rollbackManagedSkill(
    skillId: string,
    versionNumber: number,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  exportManagedSkillPackage(skillId: string, signal?: AbortSignal): Promise<ManagedSkillPackage>;
  getManagedSkillVersion(
    skillId: string,
    versionNumber: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkillVersionDetail>;
}
export function applyDesktopTenantSkillPackagesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_tenant_skill_packages_authority_config_invalid',
      'invalid skill packages authority config',
    );
  context.provide(
    DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopTenantSkillPackagesHttpProjectionV2 }),
  );
}
export const desktopTenantSkillPackagesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantSkillPackagesAuthorityV2,
});
export function createDesktopTenantSkillPackagesOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantSkillPackagesOperationsV2 {
  const run = <T>(
    input: SkillInputV2,
    operation: (authority: DesktopTenantSkillPackagesAuthorityV2) => Promise<T>,
  ) =>
    runSkillOperationV2(
      resolve,
      DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_SERVICE_V2,
      ['importPackage', 'importZip', 'listVersions', 'rollback', 'exportPackage', 'getVersion'],
      input,
      operation,
    );
  return Object.freeze({
    importTenantSkillPackage(input: SkillPackageImportInputV2) {
      const p = prepareSkillPackageImportV2(input);
      return run(p, async (a) =>
        requireSkillLifecycleV2(await a.importPackage(p.scope, p.input, p.signal), p.scope),
      );
    },
    importTenantSkillZip(input: SkillPackageZipInputV2) {
      const p = prepareSkillPackageZipV2(input);
      return run(p, async (a) =>
        requireSkillLifecycleV2(await a.importZip(p.scope, p.archive, p.input, p.signal), p.scope),
      );
    },
    listTenantSkillVersions(input: SkillPackageItemInputV2) {
      const p = prepareSkillPackageItemV2(input);
      return run(p, async (a) =>
        requireSkillVersionsV2(await a.listVersions(p.scope, p.skillId, p.signal), p.skillId),
      );
    },
    rollbackTenantSkill(input: SkillPackageVersionInputV2) {
      const p = prepareSkillPackageVersionV2(input);
      return run(p, async (a) =>
        requireDesktopTenantSkillDefinitionV2(
          await a.rollback(p.scope, p.skillId, p.versionNumber, p.expectedRevision, p.signal),
          p.scope,
          p.skillId,
        ),
      );
    },
    exportTenantSkillPackage(input: SkillPackageItemInputV2) {
      const p = prepareSkillPackageItemV2(input);
      return run(p, async (a) =>
        requireSkillPackageV2(
          await a.exportPackage(p.scope, p.skillId, p.signal),
          p.scope,
          p.skillId,
        ),
      );
    },
    getTenantSkillVersion(input: SkillPackageVersionInputV2) {
      const p = prepareSkillPackageVersionV2(input);
      return run(p, async (a) =>
        requireSkillVersionV2(
          await a.getVersion(p.scope, p.skillId, p.versionNumber, p.signal),
          p.skillId,
          p.versionNumber,
          p.scope,
        ),
      );
    },
  });
}
export function createDesktopTenantSkillPackagesClientV2(
  operations: DesktopTenantSkillPackagesOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopTenantSkillPackagesClientV2 {
  const frozen = freezeSkillConfigV2(config);
  const common = (signal?: AbortSignal): SkillInputV2 => ({
    config: frozen,
    scope: {
      authority: frozen.mode,
      tenantId: frozen.tenantId,
      projectId: frozen.projectId || null,
    },
    ...(signal === undefined ? {} : { signal }),
  });
  const importCommon = (input: ManagedSkillZipImportInput, signal?: AbortSignal): SkillInputV2 => {
    const base = common(signal);
    return {
      ...base,
      scope: {
        ...base.scope,
        projectId: frozen.mode === 'cloud' ? (input.project_id ?? null) : base.scope.projectId,
      },
    };
  };
  const client: DesktopTenantSkillPackagesClientV2 = {
    importManagedSkillPackage: (input, signal) =>
      operations.importTenantSkillPackage({ ...importCommon(input, signal), input }),
    importManagedSkillZip: (archive, input = {}, signal) =>
      operations.importTenantSkillZip({ ...importCommon(input, signal), archive, input }),
    listManagedSkillVersions: (skillId, signal) =>
      operations.listTenantSkillVersions({ ...common(signal), skillId }),
    rollbackManagedSkill: (skillId, versionNumber, expectedRevision, signal) =>
      operations.rollbackTenantSkill({
        ...common(signal),
        skillId,
        versionNumber,
        ...(expectedRevision === undefined ? {} : { expectedRevision }),
      }),
    exportManagedSkillPackage: (skillId, signal) =>
      operations.exportTenantSkillPackage({ ...common(signal), skillId }),
    getManagedSkillVersion: (skillId, versionNumber, signal) =>
      operations.getTenantSkillVersion({ ...common(signal), skillId, versionNumber }),
  };
  return Object.freeze(client);
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_skill_packages_authority_catalog_missing',
      'skill packages authority absent from catalog',
    );
  return entry.contract_digest;
}
