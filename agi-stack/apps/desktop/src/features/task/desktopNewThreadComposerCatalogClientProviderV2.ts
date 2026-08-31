import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopNewThreadComposerCatalogMethod =
  | 'listManagedAgents'
  | 'listManagedSkills'
  | 'listManagedSubAgents'
  | 'listMarketplacePlugins'
  | 'listWorkspaceAgents'
  | 'uploadSandboxFile';

export type DesktopNewThreadComposerCatalogClient = Readonly<
  Pick<DesktopApiClient, DesktopNewThreadComposerCatalogMethod>
>;

export type DesktopNewThreadComposerCatalogClientProviderReasonCodeV2 =
  'desktop_new_thread_composer_catalog_client_unpublished';

export class DesktopNewThreadComposerCatalogClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopNewThreadComposerCatalogClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopNewThreadComposerCatalogClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopNewThreadComposerCatalogClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopNewThreadComposerCatalogClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopNewThreadComposerCatalogClientBindingV2 = Readonly<{
  client: DesktopNewThreadComposerCatalogClient;
}>;

export type DesktopNewThreadComposerCatalogClientProviderV2 = Readonly<{
  publish: (
    input: DesktopNewThreadComposerCatalogClientProviderInputV2,
  ) => DesktopNewThreadComposerCatalogClientBindingV2;
  resolve: () => DesktopNewThreadComposerCatalogClientBindingV2;
}>;

export function createDesktopNewThreadComposerCatalogClientProviderV2():
  DesktopNewThreadComposerCatalogClientProviderV2 {
  let publication: DesktopNewThreadComposerCatalogClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopNewThreadComposerCatalogClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopNewThreadComposerCatalogClientProviderErrorV2(
          'desktop_new_thread_composer_catalog_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopNewThreadComposerCatalogClientBindingV2(
  input: DesktopNewThreadComposerCatalogClientProviderInputV2,
): DesktopNewThreadComposerCatalogClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  const workspaceId = config.workspaceId.trim();
  const authority = new DesktopApiClient(config);
  const client: DesktopNewThreadComposerCatalogClient = Object.freeze({
    listWorkspaceAgents: (
      ...args: Parameters<DesktopApiClient['listWorkspaceAgents']>
    ) => (workspaceId ? authority.listWorkspaceAgents(...args) : Promise.resolve([])),
    listManagedAgents: (
      ...args: Parameters<DesktopApiClient['listManagedAgents']>
    ) => authority.listManagedAgents(...args),
    listManagedSkills: (
      ...args: Parameters<DesktopApiClient['listManagedSkills']>
    ) => authority.listManagedSkills(...args),
    listMarketplacePlugins: (
      ...args: Parameters<DesktopApiClient['listMarketplacePlugins']>
    ) => authority.listMarketplacePlugins(...args),
    listManagedSubAgents: (
      ...args: Parameters<DesktopApiClient['listManagedSubAgents']>
    ) => authority.listManagedSubAgents(...args),
    uploadSandboxFile: (
      ...args: Parameters<DesktopApiClient['uploadSandboxFile']>
    ) => authority.uploadSandboxFile(...args),
  });
  return Object.freeze({ client });
}
