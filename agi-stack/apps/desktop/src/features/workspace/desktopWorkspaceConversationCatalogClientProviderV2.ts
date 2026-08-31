import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceConversationCatalogMethod = 'listConversations';

export type DesktopWorkspaceConversationCatalogClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceConversationCatalogMethod>
>;

export type DesktopWorkspaceConversationCatalogClientProviderReasonCodeV2 =
  'desktop_workspace_conversation_catalog_client_unpublished';

export class DesktopWorkspaceConversationCatalogClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceConversationCatalogClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceConversationCatalogClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceConversationCatalogClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceConversationCatalogClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceConversationCatalogClientBindingV2 = Readonly<{
  client: DesktopWorkspaceConversationCatalogClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopWorkspaceConversationCatalogClient;
}>;

export type DesktopWorkspaceConversationCatalogClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceConversationCatalogClientProviderInputV2,
  ) => DesktopWorkspaceConversationCatalogClientBindingV2;
  resolve: () => DesktopWorkspaceConversationCatalogClientBindingV2;
}>;

export function createDesktopWorkspaceConversationCatalogClientProviderV2():
  DesktopWorkspaceConversationCatalogClientProviderV2 {
  let publication: DesktopWorkspaceConversationCatalogClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceConversationCatalogClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceConversationCatalogClientProviderErrorV2(
          'desktop_workspace_conversation_catalog_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceConversationCatalogClientBindingV2(
  input: DesktopWorkspaceConversationCatalogClientProviderInputV2,
): DesktopWorkspaceConversationCatalogClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceConversationCatalogClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceConversationCatalogClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopWorkspaceConversationCatalogClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceConversationCatalogClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listConversations: (...args: Parameters<DesktopApiClient['listConversations']>) =>
      authority.listConversations(...args),
  });
}
