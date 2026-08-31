import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopTenantCatalogMethod = 'listTenants';

export type DesktopTenantCatalogClient = Readonly<
  Pick<DesktopApiClient, DesktopTenantCatalogMethod>
>;

export type DesktopTenantCatalogClientProviderReasonCodeV2 =
  'desktop_tenant_catalog_client_unpublished';

export class DesktopTenantCatalogClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopTenantCatalogClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopTenantCatalogClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopTenantCatalogClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopTenantCatalogClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopTenantCatalogClientBindingV2 = Readonly<{
  client: DesktopTenantCatalogClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopTenantCatalogClient;
}>;

export type DesktopTenantCatalogClientProviderV2 = Readonly<{
  publish: (
    input: DesktopTenantCatalogClientProviderInputV2,
  ) => DesktopTenantCatalogClientBindingV2;
  resolve: () => DesktopTenantCatalogClientBindingV2;
}>;

export function createDesktopTenantCatalogClientProviderV2():
  DesktopTenantCatalogClientProviderV2 {
  let publication: DesktopTenantCatalogClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopTenantCatalogClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopTenantCatalogClientProviderErrorV2(
          'desktop_tenant_catalog_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopTenantCatalogClientBindingV2(
  input: DesktopTenantCatalogClientProviderInputV2,
): DesktopTenantCatalogClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopTenantCatalogClient(config),
    bindOperation: (operationConfig) =>
      createDesktopTenantCatalogClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopTenantCatalogClient(
  config: DesktopRuntimeConfig,
): DesktopTenantCatalogClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listTenants: (...args: Parameters<DesktopApiClient['listTenants']>) =>
      authority.listTenants(...args),
  });
}
