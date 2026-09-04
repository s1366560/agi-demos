import type { DesktopTenantTemplatesOperationsV2 } from '../plugins/desktopTenantTemplatesAuthorityModuleV2';
import { createDesktopTenantTemplatesHttpProjectionV2 } from '../plugins/desktopTenantTemplatesHttpProjectionV2';
import {
  prepareDesktopTenantTemplatesItemV2,
  prepareDesktopTenantTemplatesLoadV2,
  prepareDesktopTenantTemplatesSeedV2,
  requireDesktopTenantTemplateDetailV2,
  requireDesktopTenantTemplateInstallV2,
  requireDesktopTenantTemplatesSnapshotV2,
  requireDesktopTenantTemplateSeedV2,
} from '../plugins/desktopTenantTemplatesOperationContractV2';

// The standalone QA pages do not activate a renderer generation host. They
// still exercise the exact production projection and operation contracts.
export function createDesktopTenantTemplatesQaOperationsV2(): DesktopTenantTemplatesOperationsV2 {
  const operations: DesktopTenantTemplatesOperationsV2 = {
    async loadTenantTemplates(input) {
      const prepared = prepareDesktopTenantTemplatesLoadV2(input);
      const authority = createDesktopTenantTemplatesHttpProjectionV2(prepared.config);
      return requireDesktopTenantTemplatesSnapshotV2(
        await authority.load(prepared.scope, prepared.query, prepared.signal),
        prepared.scope,
        prepared.query,
      );
    },
    async getTenantTemplate(input) {
      const prepared = prepareDesktopTenantTemplatesItemV2(input);
      const authority = createDesktopTenantTemplatesHttpProjectionV2(prepared.config);
      return requireDesktopTenantTemplateDetailV2(
        await authority.get(prepared.scope, prepared.templateId, prepared.signal),
        prepared.scope.tenantId,
      );
    },
    async installTenantTemplate(input) {
      const prepared = prepareDesktopTenantTemplatesItemV2(input);
      const authority = createDesktopTenantTemplatesHttpProjectionV2(prepared.config);
      return requireDesktopTenantTemplateInstallV2(
        await authority.install(prepared.scope, prepared.templateId, prepared.signal),
        prepared.scope.tenantId,
      );
    },
    async seedTenantTemplates(input) {
      const prepared = prepareDesktopTenantTemplatesSeedV2(input);
      const authority = createDesktopTenantTemplatesHttpProjectionV2(prepared.config);
      return requireDesktopTenantTemplateSeedV2(
        await authority.seed(prepared.scope, prepared.signal),
      );
    },
  };
  return Object.freeze(operations);
}
