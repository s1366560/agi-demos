import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceCatalogMethod = 'listWorkspacesForProject';

export type DesktopWorkspaceCatalogClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceCatalogMethod>
>;

export type DesktopWorkspaceCatalogClientProviderReasonCodeV2 =
  'desktop_workspace_catalog_client_unpublished';

export class DesktopWorkspaceCatalogClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceCatalogClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceCatalogClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceCatalogClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceCatalogClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceCatalogClientBindingV2 = Readonly<{
  client: DesktopWorkspaceCatalogClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopWorkspaceCatalogClient;
}>;

export type DesktopWorkspaceCatalogClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceCatalogClientProviderInputV2,
  ) => DesktopWorkspaceCatalogClientBindingV2;
  resolve: () => DesktopWorkspaceCatalogClientBindingV2;
}>;

export function createDesktopWorkspaceCatalogClientProviderV2():
  DesktopWorkspaceCatalogClientProviderV2 {
  let publication: DesktopWorkspaceCatalogClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceCatalogClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceCatalogClientProviderErrorV2(
          'desktop_workspace_catalog_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceCatalogClientBindingV2(
  input: DesktopWorkspaceCatalogClientProviderInputV2,
): DesktopWorkspaceCatalogClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceCatalogClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceCatalogClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopWorkspaceCatalogClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceCatalogClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listWorkspacesForProject: (
      ...args: Parameters<DesktopApiClient['listWorkspacesForProject']>
    ) => authority.listWorkspacesForProject(...args),
  });
}
