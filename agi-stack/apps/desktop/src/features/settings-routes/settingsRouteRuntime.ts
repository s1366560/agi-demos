import type { DesktopRuntimeConfig } from '../../types';
import {
  createDesktopTenantAgentDefinitionsRouteClientV2,
  type DesktopTenantAgentDefinitionsOperationsV2,
} from '../../plugins/desktopTenantAgentDefinitionsAuthorityModuleV2';
import { createManagementRouteController } from './managementRouteController';
import type {
  ManagementRouteBinding,
  ManagementRouteContext,
} from './managementRouteModule';
import type {
  ManagementRouteCapability,
  ManagementRouteClient,
  ManagementRouteContent,
} from './managementRouteTypes';
import { managementRouteScopeForRuntime } from './managementRouteTypes';
import { createMcpServersRouteClient } from './mcpServersRouteClient';
import {
  createPluginsRouteClient,
  type PluginsRouteAuthority,
} from './pluginsRouteClient';
import { createProviderRouteClient, type ProviderRouteAuthority } from './providerRouteClient';
import { createSkillsRouteClient, type SkillsRouteAuthority } from './skillsRouteClient';

type ManagementRouteRuntimeDependencies = Readonly<{
  createClient?: (config: DesktopRuntimeConfig) => ManagementRouteClient;
}>;

export function createProvidersRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  operations: ProviderRouteAuthority,
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-providers',
    config,
    context,
    Content,
    (runtimeConfig) => createProviderRouteClient(runtimeConfig, operations),
  );
}

export function createAgentDefinitionsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  operations: DesktopTenantAgentDefinitionsOperationsV2,
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-agent-definitions',
    config,
    context,
    Content,
    (runtimeConfig) =>
      createDesktopTenantAgentDefinitionsRouteClientV2(operations, runtimeConfig),
  );
}

export function createSkillsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  operations: SkillsRouteAuthority,
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-skills',
    config,
    context,
    Content,
    (runtimeConfig) => createSkillsRouteClient(runtimeConfig, operations),
  );
}

export function createPluginsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  pluginMarketplaceOperationsV2: PluginsRouteAuthority,
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-plugins',
    config,
    context,
    Content,
    (runtimeConfig) =>
      createPluginsRouteClient(runtimeConfig, pluginMarketplaceOperationsV2),
  );
}

export function createMcpServersRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  dependencies: ManagementRouteRuntimeDependencies = {},
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-mcp-servers',
    config,
    context,
    Content,
    dependencies.createClient ?? createMcpServersRouteClient,
  );
}

function createRuntimeBinding(
  capability: ManagementRouteCapability,
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  createClient: (config: DesktopRuntimeConfig) => ManagementRouteClient,
): ManagementRouteBinding {
  const scope = managementRouteScopeForRuntime(config, context.tenantId);
  return Object.freeze({
    controller: createManagementRouteController({
      capability,
      client: createClient(config),
      initialScope: scope,
    }),
    scope,
    Content,
  });
}
