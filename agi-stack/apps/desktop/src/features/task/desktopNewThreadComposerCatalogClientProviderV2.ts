import { DesktopApiClient } from '../../api/client';
import type { DesktopPluginMarketplaceCatalogOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import {
  createDesktopTenantAgentDefinitionsClientV2,
  type DesktopTenantAgentDefinitionsOperationsV2,
} from '../../plugins/desktopTenantAgentDefinitionsAuthorityModuleV2';
import {
  createDesktopTenantPromptTemplatesClientV2,
  type DesktopTenantPromptTemplatesOperationsV2,
} from '../../plugins/desktopTenantPromptTemplatesAuthorityModuleV2';
import type { DesktopWorkspaceRosterOperationsV2 } from '../../plugins/desktopWorkspaceRosterAuthorityModuleV2';
import {
  createDesktopTenantSubAgentDefinitionsClientV2,
  type DesktopTenantSubAgentDefinitionsOperationsV2,
} from '../../plugins/desktopTenantSubAgentDefinitionsAuthorityModuleV2';
import type { DesktopRuntimeConfig, ManagedAgentDefinition } from '../../types';

type DesktopNewThreadComposerStaticCatalogMethod =
  | 'listManagedSkills'
  | 'listMarketplacePlugins'
  | 'listWorkspaceAgents'
  | 'uploadSandboxFile';

export type DesktopNewThreadComposerCatalogClient = Readonly<
  Pick<DesktopApiClient, DesktopNewThreadComposerStaticCatalogMethod> & {
    listManagedAgents(signal?: AbortSignal): Promise<ManagedAgentDefinition[]>;
    listManagedSubAgents: ReturnType<
      typeof createDesktopTenantSubAgentDefinitionsClientV2
    >['listManagedSubAgents'];
    listPromptTemplates: ReturnType<
      typeof createDesktopTenantPromptTemplatesClientV2
    >['listPromptTemplates'];
    createPromptTemplate: ReturnType<
      typeof createDesktopTenantPromptTemplatesClientV2
    >['createPromptTemplate'];
    deletePromptTemplate: ReturnType<
      typeof createDesktopTenantPromptTemplatesClientV2
    >['deletePromptTemplate'];
  }
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
  pluginMarketplaceOperationsV2: Pick<
    DesktopPluginMarketplaceCatalogOperationsV2,
    'listMarketplacePlugins'
  >;
  workspaceRosterOperationsV2: Pick<
    DesktopWorkspaceRosterOperationsV2,
    'listWorkspaceAgents'
  >;
  tenantAgentDefinitionsOperationsV2: DesktopTenantAgentDefinitionsOperationsV2;
  tenantPromptTemplatesOperationsV2: DesktopTenantPromptTemplatesOperationsV2;
  tenantSubAgentDefinitionsOperationsV2: DesktopTenantSubAgentDefinitionsOperationsV2;
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
  const agentDefinitions = createDesktopTenantAgentDefinitionsClientV2(
    input.tenantAgentDefinitionsOperationsV2,
    config,
  );
  const subAgentDefinitions = createDesktopTenantSubAgentDefinitionsClientV2(
    input.tenantSubAgentDefinitionsOperationsV2,
    config,
  );
  const promptTemplates = createDesktopTenantPromptTemplatesClientV2(
    input.tenantPromptTemplatesOperationsV2,
    config,
  );
  const client: DesktopNewThreadComposerCatalogClient = Object.freeze({
    listWorkspaceAgents: (signal?: AbortSignal) =>
      workspaceId
        ? input.workspaceRosterOperationsV2.listWorkspaceAgents({ config, signal })
        : Promise.resolve([]),
    listManagedAgents: (signal) => agentDefinitions.listManagedAgents(signal),
    listPromptTemplates: (tenantId, signal) =>
      promptTemplates.listPromptTemplates(tenantId, signal),
    createPromptTemplate: (tenantId, value, signal) =>
      promptTemplates.createPromptTemplate(tenantId, value, signal),
    deletePromptTemplate: (templateId, signal, expectedRevision) =>
      promptTemplates.deletePromptTemplate(templateId, signal, expectedRevision),
    listManagedSkills: (
      ...args: Parameters<DesktopApiClient['listManagedSkills']>
    ) => authority.listManagedSkills(...args),
    listMarketplacePlugins: (
      ...args: Parameters<DesktopApiClient['listMarketplacePlugins']>
    ) => input.pluginMarketplaceOperationsV2.listMarketplacePlugins(config, ...args),
    listManagedSubAgents: (signal) => subAgentDefinitions.listManagedSubAgents(signal),
    uploadSandboxFile: (
      ...args: Parameters<DesktopApiClient['uploadSandboxFile']>
    ) => authority.uploadSandboxFile(...args),
  });
  return Object.freeze({ client });
}
