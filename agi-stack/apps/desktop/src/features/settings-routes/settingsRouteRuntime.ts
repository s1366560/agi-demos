import type { DesktopRuntimeConfig } from '../../types';
import { createAgentDefinitionsRouteClient } from './agentDefinitionsRouteClient';
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
import { createPluginsRouteClient } from './pluginsRouteClient';
import { createProviderRouteClient } from './providerRouteClient';
import { createSkillsRouteClient } from './skillsRouteClient';

type ManagementRouteRuntimeDependencies = Readonly<{
  createClient?: (config: DesktopRuntimeConfig) => ManagementRouteClient;
}>;

export function createProvidersRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  dependencies: ManagementRouteRuntimeDependencies = {},
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-providers',
    config,
    context,
    Content,
    dependencies.createClient ?? createProviderRouteClient,
  );
}

export function createAgentDefinitionsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  dependencies: ManagementRouteRuntimeDependencies = {},
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-agent-definitions',
    config,
    context,
    Content,
    dependencies.createClient ?? createAgentDefinitionsRouteClient,
  );
}

export function createSkillsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  dependencies: ManagementRouteRuntimeDependencies = {},
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-skills',
    config,
    context,
    Content,
    dependencies.createClient ?? createSkillsRouteClient,
  );
}

export function createPluginsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ManagementRouteContext,
  Content: ManagementRouteContent,
  dependencies: ManagementRouteRuntimeDependencies = {},
): ManagementRouteBinding {
  return createRuntimeBinding(
    'tenant-tenant-plugins',
    config,
    context,
    Content,
    dependencies.createClient ?? createPluginsRouteClient,
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
