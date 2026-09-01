import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceMessageCatalogMethod = 'listMessages';

export type DesktopWorkspaceMessageCatalogClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceMessageCatalogMethod>
>;

export type DesktopWorkspaceMessageCatalogClientProviderReasonCodeV2 =
  'desktop_workspace_message_catalog_client_unpublished';

export class DesktopWorkspaceMessageCatalogClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceMessageCatalogClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceMessageCatalogClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceMessageCatalogClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceMessageCatalogClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceMessageCatalogClientBindingV2 = Readonly<{
  client: DesktopWorkspaceMessageCatalogClient;
  bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceMessageCatalogClient;
}>;

export type DesktopWorkspaceMessageCatalogClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceMessageCatalogClientProviderInputV2,
  ) => DesktopWorkspaceMessageCatalogClientBindingV2;
  resolve: () => DesktopWorkspaceMessageCatalogClientBindingV2;
}>;

export function createDesktopWorkspaceMessageCatalogClientProviderV2():
  DesktopWorkspaceMessageCatalogClientProviderV2 {
  let publication: DesktopWorkspaceMessageCatalogClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceMessageCatalogClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceMessageCatalogClientProviderErrorV2(
          'desktop_workspace_message_catalog_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceMessageCatalogClientBindingV2(
  input: DesktopWorkspaceMessageCatalogClientProviderInputV2,
): DesktopWorkspaceMessageCatalogClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceMessageCatalogClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceMessageCatalogClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopWorkspaceMessageCatalogClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceMessageCatalogClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listMessages: (...args: Parameters<DesktopApiClient['listMessages']>) =>
      authority.listMessages(...args),
  });
}
