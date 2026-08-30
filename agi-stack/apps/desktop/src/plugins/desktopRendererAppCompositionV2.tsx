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
import { DesktopActivityInboxSurfaceV2 } from './DesktopActivityInboxSurfaceV2';
import { DesktopAuthenticatedShellSurfaceV2 } from './DesktopAuthenticatedShellSurfaceV2';
import { DesktopCommandPaletteSurfaceV2 } from './DesktopCommandPaletteSurfaceV2';
import { DesktopConversationSurfaceV2 } from './DesktopConversationSurfaceV2';
import { DesktopKeyboardShortcutsSurfaceV2 } from './DesktopKeyboardShortcutsSurfaceV2';
import { DesktopMyWorkQueueSurfaceV2 } from './DesktopMyWorkQueueSurfaceV2';
import { DesktopNewThreadComposerSurfaceV2 } from './DesktopNewThreadComposerSurfaceV2';
import { DesktopSessionCanvasSurfaceV2 } from './DesktopSessionCanvasSurfaceV2';
import { DesktopSessionWorkspaceSurfaceV2 } from './DesktopSessionWorkspaceSurfaceV2';
import { DesktopSettingsWindowSurfaceV2 } from './DesktopSettingsWindowSurfaceV2';
import { DesktopStatusBarSurfaceV2 } from './DesktopStatusBarSurfaceV2';
import { DesktopWorkspaceCollaborationSurfaceV2 } from './DesktopWorkspaceCollaborationSurfaceV2';
import { DesktopWorkbenchSurfaceV2 } from './DesktopWorkbenchSurfaceV2';
import {
  DESKTOP_CONVERSATION_RENDERER_MODULE_REF_V2,
  DESKTOP_CONVERSATION_RENDERER_MODULE_V2,
} from './desktopConversationRendererModuleV2';
import {
  DESKTOP_TOOL_RESULT_RENDERER_MODULE_REF_V2,
  DESKTOP_TOOL_RESULT_RENDERER_MODULE_V2,
} from './desktopToolResultRendererModuleV2';
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
  DESKTOP_ACTIVITY_INBOX_SURFACE_MODULE_REF_V2,
  DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2,
  DESKTOP_COMMAND_PALETTE_SURFACE_MODULE_REF_V2,
  DESKTOP_CONVERSATION_SURFACE_MODULE_REF_V2,
  DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_MODULE_REF_V2,
  DESKTOP_MY_WORK_QUEUE_SURFACE_MODULE_REF_V2,
  DESKTOP_NEW_THREAD_COMPOSER_SURFACE_MODULE_REF_V2,
  DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2,
  DESKTOP_SESSION_WORKSPACE_SURFACE_MODULE_REF_V2,
  DESKTOP_SETTINGS_WINDOW_SURFACE_MODULE_REF_V2,
  DESKTOP_STATUS_BAR_SURFACE_MODULE_REF_V2,
  DESKTOP_WORKSPACE_COLLABORATION_SURFACE_MODULE_REF_V2,
  DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2,
  type DesktopRendererCompositionPortV2,
  type DesktopRendererWorkbenchSurfaceV2,
} from './desktopRendererCompositionPortV2';
import type { AuthorizedUiSlotDefinitionV2, UiSlotDefinition } from './uiSlotRegistry';

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
    resolveActivityInboxSurface: (definition: UiSlotDefinition) =>
      validActivityInboxDefinitionV2(definition) ? DesktopActivityInboxSurfaceV2 : null,
    resolveAuthenticatedShellSurface: (definition: UiSlotDefinition) =>
      validAuthenticatedShellDefinitionV2(definition) ? DesktopAuthenticatedShellSurfaceV2 : null,
    resolveCommandPaletteSurface: (definition: UiSlotDefinition) =>
      validCommandPaletteDefinitionV2(definition) ? DesktopCommandPaletteSurfaceV2 : null,
    resolveConversationSurface: (definition: UiSlotDefinition) =>
      validConversationDefinitionV2(definition) ? DesktopConversationSurfaceV2 : null,
    resolveKeyboardShortcutsSurface: (definition: UiSlotDefinition) =>
      validKeyboardShortcutsDefinitionV2(definition)
        ? DesktopKeyboardShortcutsSurfaceV2
        : null,
    resolveStatusBarSurface: (definition: UiSlotDefinition) =>
      validStatusBarDefinitionV2(definition) ? DesktopStatusBarSurfaceV2 : null,
    resolveConversationRendererModule: (definition: AuthorizedUiSlotDefinitionV2) =>
      validConversationRendererDefinitionV2(definition)
        ? DESKTOP_CONVERSATION_RENDERER_MODULE_V2
        : null,
    resolveToolResultRendererModule: (definition: AuthorizedUiSlotDefinitionV2) =>
      validToolResultRendererDefinitionV2(definition)
        ? DESKTOP_TOOL_RESULT_RENDERER_MODULE_V2
        : null,
    resolveMyWorkQueueSurface: (definition: UiSlotDefinition) =>
      validMyWorkQueueDefinitionV2(definition) ? DesktopMyWorkQueueSurfaceV2 : null,
    resolveNewThreadComposerSurface: (definition: UiSlotDefinition) =>
      validNewThreadComposerDefinitionV2(definition)
        ? DesktopNewThreadComposerSurfaceV2
        : null,
    resolveSettingsWindowSurface: (definition: UiSlotDefinition) =>
      validSettingsWindowDefinitionV2(definition) ? DesktopSettingsWindowSurfaceV2 : null,
    resolveSessionCanvasSurface: (definition: UiSlotDefinition) =>
      validSessionCanvasDefinitionV2(definition) ? DesktopSessionCanvasSurfaceV2 : null,
    resolveSessionWorkspaceSurface: (definition: UiSlotDefinition) =>
      validSessionWorkspaceDefinitionV2(definition) ? DesktopSessionWorkspaceSurfaceV2 : null,
    resolveWorkspaceCollaborationSurface: (definition: UiSlotDefinition) =>
      validWorkspaceCollaborationDefinitionV2(definition)
        ? DesktopWorkspaceCollaborationSurfaceV2
        : null,
    resolveWorkbenchSurface: (definition: UiSlotDefinition) =>
      validWorkbenchDefinitionV2(definition) ? DesktopWorkbenchSurfaceV2 : null,
  });
}

function validActivityInboxDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'activity_inbox_surface' &&
    definition.id === 'activity-inbox' &&
    definition.contract === 'ui-builtin:desktop-activity-inbox-surface' &&
    definition.moduleRef === DESKTOP_ACTIVITY_INBOX_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.activity-inbox' &&
    definition.sandbox
  );
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

function validCommandPaletteDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'command_palette_surface' &&
    definition.id === 'command-palette' &&
    definition.contract === 'ui-builtin:desktop-command-palette-surface' &&
    definition.moduleRef === DESKTOP_COMMAND_PALETTE_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.command-palette' &&
    definition.sandbox
  );
}

function validConversationDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'conversation_surface' &&
    definition.id === 'conversation' &&
    definition.contract === 'ui-builtin:desktop-conversation-surface' &&
    definition.moduleRef === DESKTOP_CONVERSATION_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.conversation' &&
    definition.sandbox
  );
}

function validConversationRendererDefinitionV2(
  definition: AuthorizedUiSlotDefinitionV2,
): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'conversation_renderer' &&
    definition.id === 'conversation-renderer' &&
    definition.contract === 'ui-builtin:desktop-conversation-renderer' &&
    definition.moduleRef === DESKTOP_CONVERSATION_RENDERER_MODULE_REF_V2 &&
    definition.permission === 'ui.conversation.renderer' &&
    definition.sandbox &&
    definition.grantedPermissions.includes(definition.permission)
  );
}

function validToolResultRendererDefinitionV2(
  definition: AuthorizedUiSlotDefinitionV2,
): boolean {
  return (
    definition.pluginId === 'builtin-ui' &&
    definition.slot === 'tool_result_renderer' &&
    definition.id === 'structured-tool-result' &&
    definition.contract === 'ui-builtin:structured-tool-result' &&
    definition.moduleRef === DESKTOP_TOOL_RESULT_RENDERER_MODULE_REF_V2 &&
    definition.permission === 'ui.render' &&
    definition.sandbox &&
    definition.grantedPermissions.includes(definition.permission)
  );
}

function validMyWorkQueueDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'my_work_queue_surface' &&
    definition.id === 'my-work-queue' &&
    definition.contract === 'ui-builtin:desktop-my-work-queue-surface' &&
    definition.moduleRef === DESKTOP_MY_WORK_QUEUE_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.my-work-queue' &&
    definition.sandbox
  );
}

function validKeyboardShortcutsDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'keyboard_shortcuts_surface' &&
    definition.id === 'keyboard-shortcuts' &&
    definition.contract === 'ui-builtin:desktop-keyboard-shortcuts-surface' &&
    definition.moduleRef === DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.keyboard-shortcuts' &&
    definition.sandbox
  );
}

function validStatusBarDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'status_bar_surface' &&
    definition.id === 'status-bar' &&
    definition.contract === 'ui-builtin:desktop-status-bar-surface' &&
    definition.moduleRef === DESKTOP_STATUS_BAR_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.status-bar' &&
    definition.sandbox
  );
}

function validNewThreadComposerDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'new_thread_composer_surface' &&
    definition.id === 'new-thread-composer' &&
    definition.contract === 'ui-builtin:desktop-new-thread-composer-surface' &&
    definition.moduleRef === DESKTOP_NEW_THREAD_COMPOSER_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.new-thread-composer' &&
    definition.sandbox
  );
}

function validSettingsWindowDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'settings_window_surface' &&
    definition.id === 'settings-window' &&
    definition.contract === 'ui-builtin:desktop-settings-window-surface' &&
    definition.moduleRef === DESKTOP_SETTINGS_WINDOW_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.settings-window' &&
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

function validSessionWorkspaceDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'session_workspace_surface' &&
    definition.id === 'session-workspace' &&
    definition.contract === 'ui-builtin:desktop-session-workspace-surface' &&
    definition.moduleRef === DESKTOP_SESSION_WORKSPACE_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.session-workspace' &&
    definition.sandbox
  );
}

function validWorkspaceCollaborationDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'workspace_collaboration_surface' &&
    definition.id === 'workspace-collaboration' &&
    definition.contract === 'ui-builtin:desktop-workspace-collaboration-surface' &&
    definition.moduleRef === DESKTOP_WORKSPACE_COLLABORATION_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.workspace-collaboration' &&
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
