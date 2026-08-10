import {
  createTenantAdminController,
  type TenantAdminControllerCore,
} from './tenantAdminController';
import { saveBlobWithDesktopDialog } from '../runtime/nativeFileBridge';
import type { TenantAdminScope } from './tenantAdminHttp';
import type {
  TenantAuditClient,
  TenantAuditExportFormat,
  TenantAuditQuery,
} from './tenantAuditClient';
import {
  buildTenantAuditPresentation,
  type TenantAuditViewModel,
} from './tenantAuditPresentationModel';

export type TenantAuditController = TenantAdminControllerCore<
  TenantAdminScope,
  TenantAuditViewModel
> &
  Readonly<{
    setQuery: (query: TenantAuditQuery) => Promise<void>;
    exportLogs: (format: TenantAuditExportFormat) => Promise<DesktopFileSaveResult>;
  }>;

export function createTenantAuditController({
  client,
  initialScope,
  initialQuery = {},
  saveExport = saveBlobWithDesktopDialog,
}: Readonly<{
  client: TenantAuditClient;
  initialScope: TenantAdminScope;
  initialQuery?: TenantAuditQuery;
  saveExport?: typeof saveBlobWithDesktopDialog;
}>): TenantAuditController {
  let activeScope = initialScope;
  let activeQuery = initialQuery;
  const core = createTenantAdminController({
    initialScope,
    reasonPrefix: 'tenant_audit',
    loadAuthority: (scope, options) => client.load(scope, activeQuery, options),
    isEmpty: (data) => data.entries.length === 0,
    buildPresentation: buildTenantAuditPresentation,
  });
  return Object.freeze({
    ...core,
    async load(scope) {
      activeScope = scope;
      await core.load(scope);
    },
    async setQuery(query) {
      activeQuery = Object.freeze({ ...query });
      await core.load(activeScope);
    },
    async exportLogs(format) {
      let result: DesktopFileSaveResult = Object.freeze({ status: 'cancelled' });
      await core.runAction('export', async (scope, signal) => {
        const exported = await client.exportLogs(scope, format, activeQuery, { signal });
        result = await saveExport(exported);
      });
      return result;
    },
  });
}
