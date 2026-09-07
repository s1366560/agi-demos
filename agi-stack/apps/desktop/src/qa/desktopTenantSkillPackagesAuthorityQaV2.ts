import type { DesktopTenantSkillPackagesOperationsV2 } from '../plugins/desktopTenantSkillPackagesAuthorityModuleV2';
import { createDesktopTenantSkillPackagesHttpProjectionV2 } from '../plugins/desktopTenantSkillPackagesHttpProjectionV2';
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
} from '../plugins/desktopTenantSkillPackagesOperationContractV2';
import type { SkillInputV2 } from '../plugins/desktopTenantSkillOperationSupportV2';
import { requireDesktopTenantSkillDefinitionV2 } from '../plugins/desktopTenantSkillDefinitionsOperationContractV2';

// Standalone QA shares production contracts and HTTP transport; it does not claim native lease evidence.
export function createDesktopTenantSkillPackagesQaOperationsV2(): DesktopTenantSkillPackagesOperationsV2 {
  const run = <T>(
    input: SkillInputV2,
    operation: (authority: DesktopTenantSkillPackagesAuthorityV2) => Promise<T>,
  ) => operation(createDesktopTenantSkillPackagesHttpProjectionV2(input.config));
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
