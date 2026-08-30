import {
  createAppAuthenticationRouteRegistry,
  createAppAuxiliaryRouteRegistry,
  createAppProjectAdministrationRouteRegistry,
  createAppProjectAgentRouteRegistry,
  createAppProjectDiscoveryRouteRegistry,
  createAppProjectKnowledgeRouteRegistry,
  createAppProjectWorkspaceRouteRegistry,
  createAppRuntimeInfrastructureRouteRegistry,
  createAppTenantAgentBuildingRouteRegistry,
  createAppTenantCoreRouteRegistry,
  createAppTenantCreationRouteRegistry,
  createAppTenantExtensionsIntegrationsRouteRegistry,
  createAppTenantGovernanceRouteRegistry,
  type AppRouteRegistryRefs,
} from '../features/navigation/appRouteRegistry';
import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteRegistry } from '../features/navigation/desktopRouteRegistry';
import { DesktopAuthenticatedShellSurfaceV2 } from './DesktopAuthenticatedShellSurfaceV2';
import { DesktopSessionCanvasSurfaceV2 } from './DesktopSessionCanvasSurfaceV2';
import { DesktopWorkbenchSurfaceV2 } from './DesktopWorkbenchSurfaceV2';
import {
  DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_CREATION_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_GOVERNANCE_ROUTE_ARTIFACT_ID_V2,
} from './desktopRendererArtifactCatalogV2';
import {
  DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2,
  DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2,
  DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2,
  type DesktopRendererCompositionPortV2,
  type DesktopRendererWorkbenchSurfaceV2,
} from './desktopRendererCompositionPortV2';
import type { UiSlotDefinition } from './uiSlotRegistry';

type AppRouteRegistryFactoryV2 = (
  refs: AppRouteRegistryRefs,
) => DesktopRouteRegistry<DesktopRouteModule>;

const APP_ROUTE_REGISTRY_FACTORIES_V2 = new Map<string, AppRouteRegistryFactoryV2>([
  [DESKTOP_TENANT_CREATION_ROUTE_ARTIFACT_ID_V2, createAppTenantCreationRouteRegistry],
  [DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2, createAppAuxiliaryRouteRegistry],
  [DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2, createAppProjectKnowledgeRouteRegistry],
  [DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2, createAppProjectAgentRouteRegistry],
  [
    DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2,
    createAppProjectAdministrationRouteRegistry,
  ],
  [
    DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2,
    createAppRuntimeInfrastructureRouteRegistry,
  ],
  [DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2, createAppProjectWorkspaceRouteRegistry],
  [DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2, createAppProjectDiscoveryRouteRegistry],
  [DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2, createAppTenantCoreRouteRegistry],
  [DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2, createAppTenantAgentBuildingRouteRegistry],
  [
    DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2,
    createAppTenantExtensionsIntegrationsRouteRegistry,
  ],
  [DESKTOP_TENANT_GOVERNANCE_ROUTE_ARTIFACT_ID_V2, createAppTenantGovernanceRouteRegistry],
]);

export function createDesktopRendererAppCompositionPortV2(
  refs: AppRouteRegistryRefs,
): DesktopRendererCompositionPortV2 {
  return Object.freeze({
    createAuthenticationRouteRegistry: () => createAppAuthenticationRouteRegistry(refs),
    createRouteRegistry: (artifactId: string) => {
      const factory = APP_ROUTE_REGISTRY_FACTORIES_V2.get(artifactId);
      if (factory === undefined) {
        throw new Error(`desktop_renderer_route_composition_missing:${artifactId}`);
      }
      return factory(refs);
    },
    resolveAuthenticatedShellSurface: (definition: UiSlotDefinition) =>
      validAuthenticatedShellDefinitionV2(definition) ? DesktopAuthenticatedShellSurfaceV2 : null,
    resolveSessionCanvasSurface: (definition: UiSlotDefinition) =>
      validSessionCanvasDefinitionV2(definition) ? DesktopSessionCanvasSurfaceV2 : null,
    resolveWorkbenchSurface: (definition: UiSlotDefinition) =>
      validWorkbenchDefinitionV2(definition) ? DesktopWorkbenchSurfaceV2 : null,
  });
}

function validAuthenticatedShellDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'authenticated_shell_surface' &&
    definition.id === 'authenticated-shell' &&
    definition.contract === 'ui-builtin:desktop-authenticated-shell-surface' &&
    definition.moduleRef === DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.authenticated-shell' &&
    definition.sandbox
  );
}

function validSessionCanvasDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'session_canvas_surface' &&
    definition.id === 'session-canvas' &&
    definition.contract === 'ui-builtin:desktop-session-canvas-surface' &&
    definition.moduleRef === DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.session-canvas' &&
    definition.sandbox
  );
}

function validWorkbenchDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'workbench_surface' &&
    definition.id === 'workbench' &&
    definition.contract === 'ui-builtin:desktop-workbench-surface' &&
    definition.moduleRef === DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.workbench' &&
    definition.sandbox
  );
}
