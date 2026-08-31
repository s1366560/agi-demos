import type { ComponentType } from 'react';

import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteRegistry } from '../features/navigation/desktopRouteRegistry';
import type { DesktopActivityInboxSurfacePropsV2 } from './DesktopActivityInboxSurfaceV2';
import type { DesktopAuthenticatedShellViewModelV2 } from './DesktopAuthenticatedShellSurfaceV2';
import type { DesktopCommandPaletteSurfacePropsV2 } from './DesktopCommandPaletteSurfaceV2';
import type { DesktopConversationSurfacePropsV2 } from './DesktopConversationSurfaceV2';
import type { DesktopKeyboardShortcutsSurfacePropsV2 } from './DesktopKeyboardShortcutsSurfaceV2';
import type { DesktopMyWorkQueueSurfacePropsV2 } from './DesktopMyWorkQueueSurfaceV2';
import type { DesktopNewThreadComposerSurfacePropsV2 } from './DesktopNewThreadComposerSurfaceV2';
import type { DesktopRightSidebarSurfacePropsV2 } from './DesktopRightSidebarSurfaceV2';
import type { DesktopSessionCanvasSurfacePropsV2 } from './DesktopSessionCanvasSurfaceV2';
import type { DesktopSessionWorkspaceSurfacePropsV2 } from './DesktopSessionWorkspaceSurfaceV2';
import type { DesktopSettingsWindowSurfacePropsV2 } from './DesktopSettingsWindowSurfaceV2';
import type { DesktopSidebarSurfacePropsV2 } from './DesktopSidebarSurfaceV2';
import type { DesktopStatusBarSurfacePropsV2 } from './DesktopStatusBarSurfaceV2';
import type { DesktopTitlebarSurfacePropsV2 } from './DesktopTitlebarSurfaceV2';
import type { DesktopWorkspaceCollaborationSurfacePropsV2 } from './DesktopWorkspaceCollaborationSurfaceV2';
import type { DesktopWorkspaceCreateSurfacePropsV2 } from './DesktopWorkspaceCreateSurfaceV2';
import type { DesktopWorkspaceSettingsSurfacePropsV2 } from './DesktopWorkspaceSettingsSurfaceV2';
import type { DesktopWorkbenchTabBarSurfacePropsV2 } from './DesktopWorkbenchTabBarSurfaceV2';
import type { DesktopWorkbenchSurfaceViewModelV2 } from './DesktopWorkbenchSurfaceV2';
import type { DesktopConversationRendererModuleV2 } from './desktopConversationRendererModuleV2';
import type { DesktopRendererAuthorityStateV2 } from './desktopRendererAuthorityStateV2';
import type { DesktopToolResultRendererModuleV2 } from './desktopToolResultRendererModuleV2';
import type { AuthorizedUiSlotDefinitionV2, UiSlotDefinition } from './uiSlotRegistry';

export const DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-authenticated-shell-surface' as const;
export const DESKTOP_CONVERSATION_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-conversation-surface' as const;
export const DESKTOP_COMMAND_PALETTE_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-command-palette-surface' as const;
export const DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-keyboard-shortcuts-surface' as const;
export const DESKTOP_STATUS_BAR_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-status-bar-surface' as const;
export const DESKTOP_TITLEBAR_SURFACE_MODULE_REF_V2 = 'builtin:desktop-titlebar-surface' as const;
export const DESKTOP_SIDEBAR_SURFACE_MODULE_REF_V2 = 'builtin:desktop-sidebar-surface' as const;
export const DESKTOP_RIGHT_SIDEBAR_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-right-sidebar-surface' as const;
export const DESKTOP_SETTINGS_WINDOW_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-settings-window-surface' as const;
export const DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-session-canvas-surface' as const;
export const DESKTOP_SESSION_WORKSPACE_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-session-workspace-surface' as const;
export const DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2 = 'builtin:desktop-workbench-surface' as const;
export const DESKTOP_ACTIVITY_INBOX_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-activity-inbox-surface' as const;
export const DESKTOP_MY_WORK_QUEUE_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-my-work-queue-surface' as const;
export const DESKTOP_NEW_THREAD_COMPOSER_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-new-thread-composer-surface' as const;
export const DESKTOP_WORKSPACE_COLLABORATION_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-workspace-collaboration-surface' as const;
export const DESKTOP_WORKSPACE_CREATE_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-workspace-create-surface' as const;
export const DESKTOP_WORKSPACE_SETTINGS_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-workspace-settings-surface' as const;
export const DESKTOP_WORKBENCH_TAB_BAR_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-workbench-tab-bar-surface' as const;

export type DesktopRendererActivityInboxSurfaceV2 =
  ComponentType<DesktopActivityInboxSurfacePropsV2>;
export type DesktopRendererConversationSurfaceV2 =
  ComponentType<DesktopConversationSurfacePropsV2>;
export type DesktopRendererCommandPaletteSurfaceV2 =
  ComponentType<DesktopCommandPaletteSurfacePropsV2>;
export type DesktopRendererKeyboardShortcutsSurfaceV2 =
  ComponentType<DesktopKeyboardShortcutsSurfacePropsV2>;
export type DesktopRendererStatusBarSurfaceV2 = ComponentType<DesktopStatusBarSurfacePropsV2>;
export type DesktopRendererTitlebarSurfaceV2 = ComponentType<DesktopTitlebarSurfacePropsV2>;
export type DesktopRendererSidebarSurfaceV2 = ComponentType<DesktopSidebarSurfacePropsV2>;
export type DesktopRendererRightSidebarSurfaceV2 =
  ComponentType<DesktopRightSidebarSurfacePropsV2>;
export type DesktopRendererMyWorkQueueSurfaceV2 =
  ComponentType<DesktopMyWorkQueueSurfacePropsV2>;
export type DesktopRendererNewThreadComposerSurfaceV2 =
  ComponentType<DesktopNewThreadComposerSurfacePropsV2>;
export type DesktopRendererSettingsWindowSurfaceV2 =
  ComponentType<DesktopSettingsWindowSurfacePropsV2>;
export type DesktopRendererSessionWorkspaceSurfaceV2 =
  ComponentType<DesktopSessionWorkspaceSurfacePropsV2>;
export type DesktopRendererWorkspaceCollaborationSurfaceV2 =
  ComponentType<DesktopWorkspaceCollaborationSurfacePropsV2>;
export type DesktopRendererWorkspaceCreateSurfaceV2 =
  ComponentType<DesktopWorkspaceCreateSurfacePropsV2>;
export type DesktopRendererWorkspaceSettingsSurfaceV2 =
  ComponentType<DesktopWorkspaceSettingsSurfacePropsV2>;
export type DesktopRendererWorkbenchTabBarSurfaceV2 =
  ComponentType<DesktopWorkbenchTabBarSurfacePropsV2>;

export interface DesktopRendererAuthenticatedShellSurfacePropsV2 {
  readonly viewModel: DesktopAuthenticatedShellViewModelV2;
}

export type DesktopRendererAuthenticatedShellSurfaceV2 =
  ComponentType<DesktopRendererAuthenticatedShellSurfacePropsV2>;

export type DesktopRendererSessionCanvasSurfaceV2 =
  ComponentType<DesktopSessionCanvasSurfacePropsV2>;

export interface DesktopRendererWorkbenchSurfacePropsV2 {
  readonly viewModel: DesktopWorkbenchSurfaceViewModelV2;
}

export type DesktopRendererWorkbenchSurfaceV2 =
  ComponentType<DesktopRendererWorkbenchSurfacePropsV2>;

export interface DesktopRendererCompositionPortV2 {
  readonly createAuthenticationRouteRegistry: () => DesktopRouteRegistry<DesktopRouteModule>;
  readonly createRouteRegistry: (artifactId: string) => DesktopRouteRegistry<DesktopRouteModule>;
  readonly resolveActivityInboxSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererActivityInboxSurfaceV2 | null;
  readonly resolveAuthenticatedShellSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererAuthenticatedShellSurfaceV2 | null;
  readonly resolveCommandPaletteSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererCommandPaletteSurfaceV2 | null;
  readonly resolveConversationSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererConversationSurfaceV2 | null;
  readonly resolveKeyboardShortcutsSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererKeyboardShortcutsSurfaceV2 | null;
  readonly resolveStatusBarSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererStatusBarSurfaceV2 | null;
  readonly resolveTitlebarSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererTitlebarSurfaceV2 | null;
  readonly resolveSidebarSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererSidebarSurfaceV2 | null;
  readonly resolveRightSidebarSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererRightSidebarSurfaceV2 | null;
  readonly resolveConversationRendererModule: (
    definition: AuthorizedUiSlotDefinitionV2,
  ) => DesktopConversationRendererModuleV2 | null;
  readonly resolveToolResultRendererModule: (
    definition: AuthorizedUiSlotDefinitionV2,
  ) => DesktopToolResultRendererModuleV2 | null;
  readonly resolveMyWorkQueueSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererMyWorkQueueSurfaceV2 | null;
  readonly resolveNewThreadComposerSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererNewThreadComposerSurfaceV2 | null;
  readonly resolveSettingsWindowSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererSettingsWindowSurfaceV2 | null;
  readonly resolveSessionCanvasSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererSessionCanvasSurfaceV2 | null;
  readonly resolveSessionWorkspaceSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererSessionWorkspaceSurfaceV2 | null;
  readonly resolveWorkspaceCollaborationSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererWorkspaceCollaborationSurfaceV2 | null;
  readonly resolveWorkspaceCreateSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererWorkspaceCreateSurfaceV2 | null;
  readonly resolveWorkspaceSettingsSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererWorkspaceSettingsSurfaceV2 | null;
  readonly resolveWorkbenchTabBarSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererWorkbenchTabBarSurfaceV2 | null;
  readonly resolveWorkbenchSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererWorkbenchSurfaceV2 | null;
}

export type DesktopRendererAuthenticatedShellCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererAuthenticatedShellSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_authenticated_shell_contribution_ambiguous'
        | 'desktop_renderer_authenticated_shell_contribution_missing'
        | 'desktop_renderer_authenticated_shell_module_unavailable'
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable';
    }>;

export type DesktopRendererCommandPaletteCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererCommandPaletteSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_command_palette_contribution_ambiguous'
        | 'desktop_renderer_command_palette_contribution_missing'
        | 'desktop_renderer_command_palette_module_unavailable'
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable';
    }>;

export type DesktopRendererWorkbenchCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererWorkbenchSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_workbench_contribution_ambiguous'
        | 'desktop_renderer_workbench_contribution_missing'
        | 'desktop_renderer_workbench_module_unavailable';
    }>;

export type DesktopRendererConversationCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererConversationSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_conversation_contribution_ambiguous'
        | 'desktop_renderer_conversation_contribution_missing'
        | 'desktop_renderer_conversation_module_unavailable'
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable';
    }>;

export type DesktopRendererSessionCanvasCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererSessionCanvasSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_session_canvas_contribution_ambiguous'
        | 'desktop_renderer_session_canvas_contribution_missing'
        | 'desktop_renderer_session_canvas_module_unavailable';
    }>;

export type DesktopRendererKeyboardShortcutsCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererKeyboardShortcutsSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_keyboard_shortcuts_contribution_ambiguous'
        | 'desktop_renderer_keyboard_shortcuts_contribution_missing'
        | 'desktop_renderer_keyboard_shortcuts_module_unavailable';
    }>;

export type DesktopRendererStatusBarCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererStatusBarSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_status_bar_contribution_ambiguous'
        | 'desktop_renderer_status_bar_contribution_missing'
        | 'desktop_renderer_status_bar_module_unavailable';
    }>;

export type DesktopRendererTitlebarCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererTitlebarSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_titlebar_contribution_ambiguous'
        | 'desktop_renderer_titlebar_contribution_missing'
        | 'desktop_renderer_titlebar_module_unavailable';
    }>;

export type DesktopRendererSidebarCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererSidebarSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_sidebar_contribution_ambiguous'
        | 'desktop_renderer_sidebar_contribution_missing'
        | 'desktop_renderer_sidebar_module_unavailable';
    }>;

export type DesktopRendererRightSidebarCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererRightSidebarSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_right_sidebar_contribution_ambiguous'
        | 'desktop_renderer_right_sidebar_contribution_missing'
        | 'desktop_renderer_right_sidebar_module_unavailable';
    }>;

export type DesktopRendererSettingsWindowCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererSettingsWindowSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_settings_window_contribution_ambiguous'
        | 'desktop_renderer_settings_window_contribution_missing'
        | 'desktop_renderer_settings_window_module_unavailable';
    }>;

export type DesktopRendererSessionWorkspaceCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererSessionWorkspaceSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_session_workspace_contribution_ambiguous'
        | 'desktop_renderer_session_workspace_contribution_missing'
        | 'desktop_renderer_session_workspace_module_unavailable';
    }>;

export type DesktopRendererActivityInboxCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererActivityInboxSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_activity_inbox_contribution_ambiguous'
        | 'desktop_renderer_activity_inbox_contribution_missing'
        | 'desktop_renderer_activity_inbox_module_unavailable'
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable';
    }>;

export type DesktopRendererMyWorkQueueCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererMyWorkQueueSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_my_work_queue_contribution_ambiguous'
        | 'desktop_renderer_my_work_queue_contribution_missing'
        | 'desktop_renderer_my_work_queue_module_unavailable';
    }>;

export type DesktopRendererNewThreadComposerCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererNewThreadComposerSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_new_thread_composer_contribution_ambiguous'
        | 'desktop_renderer_new_thread_composer_contribution_missing'
        | 'desktop_renderer_new_thread_composer_module_unavailable';
    }>;

export type DesktopRendererWorkspaceCollaborationCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererWorkspaceCollaborationSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_workspace_collaboration_contribution_ambiguous'
        | 'desktop_renderer_workspace_collaboration_contribution_missing'
        | 'desktop_renderer_workspace_collaboration_module_unavailable';
    }>;

export type DesktopRendererWorkspaceCreateCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererWorkspaceCreateSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_workspace_create_contribution_ambiguous'
        | 'desktop_renderer_workspace_create_contribution_missing'
        | 'desktop_renderer_workspace_create_module_unavailable';
    }>;

export type DesktopRendererWorkspaceSettingsCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererWorkspaceSettingsSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_workspace_settings_contribution_ambiguous'
        | 'desktop_renderer_workspace_settings_contribution_missing'
        | 'desktop_renderer_workspace_settings_module_unavailable';
    }>;

export type DesktopRendererWorkbenchTabBarCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: DesktopRendererWorkbenchTabBarSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'desktop_renderer_generation_disabled'
        | 'desktop_renderer_generation_unavailable'
        | 'desktop_renderer_workbench_tab_bar_contribution_ambiguous'
        | 'desktop_renderer_workbench_tab_bar_contribution_missing'
        | 'desktop_renderer_workbench_tab_bar_module_unavailable';
    }>;

export function projectDesktopAuthenticatedShellCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererAuthenticatedShellCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableAuthenticatedShellV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableAuthenticatedShellV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'authenticated_shell_surface',
  );
  if (definitions.length === 0) {
    return unavailableAuthenticatedShellV2(
      'desktop_renderer_authenticated_shell_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableAuthenticatedShellV2(
      'desktop_renderer_authenticated_shell_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveAuthenticatedShellSurface(definitions[0]);
  if (Surface === null) {
    return unavailableAuthenticatedShellV2(
      'desktop_renderer_authenticated_shell_module_unavailable',
    );
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopCommandPaletteCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererCommandPaletteCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableCommandPaletteV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableCommandPaletteV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'command_palette_surface',
  );
  if (definitions.length === 0) {
    return unavailableCommandPaletteV2(
      'desktop_renderer_command_palette_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableCommandPaletteV2(
      'desktop_renderer_command_palette_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveCommandPaletteSurface(definitions[0]);
  if (Surface === null) {
    return unavailableCommandPaletteV2('desktop_renderer_command_palette_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopWorkspaceCreateCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererWorkspaceCreateCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableWorkspaceCreateV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableWorkspaceCreateV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'workspace_create_surface',
  );
  if (definitions.length === 0) {
    return unavailableWorkspaceCreateV2(
      'desktop_renderer_workspace_create_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableWorkspaceCreateV2(
      'desktop_renderer_workspace_create_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveWorkspaceCreateSurface(definitions[0]);
  if (Surface === null) {
    return unavailableWorkspaceCreateV2('desktop_renderer_workspace_create_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopWorkspaceSettingsCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererWorkspaceSettingsCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableWorkspaceSettingsV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableWorkspaceSettingsV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'workspace_settings_surface',
  );
  if (definitions.length === 0) {
    return unavailableWorkspaceSettingsV2(
      'desktop_renderer_workspace_settings_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableWorkspaceSettingsV2(
      'desktop_renderer_workspace_settings_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveWorkspaceSettingsSurface(definitions[0]);
  if (Surface === null) {
    return unavailableWorkspaceSettingsV2(
      'desktop_renderer_workspace_settings_module_unavailable',
    );
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopWorkbenchTabBarCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererWorkbenchTabBarCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableWorkbenchTabBarV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableWorkbenchTabBarV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'workbench_tab_bar_surface',
  );
  if (definitions.length === 0) {
    return unavailableWorkbenchTabBarV2(
      'desktop_renderer_workbench_tab_bar_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableWorkbenchTabBarV2(
      'desktop_renderer_workbench_tab_bar_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveWorkbenchTabBarSurface(definitions[0]);
  if (Surface === null) {
    return unavailableWorkbenchTabBarV2(
      'desktop_renderer_workbench_tab_bar_module_unavailable',
    );
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopWorkbenchCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererWorkbenchCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableWorkbenchV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableWorkbenchV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(({ slot }) => slot === 'workbench_surface');
  if (definitions.length === 0) {
    return unavailableWorkbenchV2('desktop_renderer_workbench_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableWorkbenchV2('desktop_renderer_workbench_contribution_ambiguous');
  }
  const Surface = composition.resolveWorkbenchSurface(definitions[0]);
  if (Surface === null) {
    return unavailableWorkbenchV2('desktop_renderer_workbench_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopConversationCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererConversationCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableConversationV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableConversationV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'conversation_surface',
  );
  if (definitions.length === 0) {
    return unavailableConversationV2('desktop_renderer_conversation_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableConversationV2('desktop_renderer_conversation_contribution_ambiguous');
  }
  const Surface = composition.resolveConversationSurface(definitions[0]);
  if (Surface === null) {
    return unavailableConversationV2('desktop_renderer_conversation_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopSessionCanvasCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererSessionCanvasCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableSessionCanvasV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableSessionCanvasV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'session_canvas_surface',
  );
  if (definitions.length === 0) {
    return unavailableSessionCanvasV2('desktop_renderer_session_canvas_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableSessionCanvasV2('desktop_renderer_session_canvas_contribution_ambiguous');
  }
  const Surface = composition.resolveSessionCanvasSurface(definitions[0]);
  if (Surface === null) {
    return unavailableSessionCanvasV2('desktop_renderer_session_canvas_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopKeyboardShortcutsCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererKeyboardShortcutsCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableKeyboardShortcutsV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableKeyboardShortcutsV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'keyboard_shortcuts_surface',
  );
  if (definitions.length === 0) {
    return unavailableKeyboardShortcutsV2(
      'desktop_renderer_keyboard_shortcuts_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableKeyboardShortcutsV2(
      'desktop_renderer_keyboard_shortcuts_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveKeyboardShortcutsSurface(definitions[0]);
  if (Surface === null) {
    return unavailableKeyboardShortcutsV2(
      'desktop_renderer_keyboard_shortcuts_module_unavailable',
    );
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopStatusBarCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererStatusBarCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableStatusBarV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableStatusBarV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(({ slot }) => slot === 'status_bar_surface');
  if (definitions.length === 0) {
    return unavailableStatusBarV2('desktop_renderer_status_bar_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableStatusBarV2('desktop_renderer_status_bar_contribution_ambiguous');
  }
  const Surface = composition.resolveStatusBarSurface(definitions[0]);
  if (Surface === null) {
    return unavailableStatusBarV2('desktop_renderer_status_bar_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopTitlebarCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererTitlebarCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableTitlebarV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableTitlebarV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(({ slot }) => slot === 'titlebar_surface');
  if (definitions.length === 0) {
    return unavailableTitlebarV2('desktop_renderer_titlebar_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableTitlebarV2('desktop_renderer_titlebar_contribution_ambiguous');
  }
  const Surface = composition.resolveTitlebarSurface(definitions[0]);
  if (Surface === null) {
    return unavailableTitlebarV2('desktop_renderer_titlebar_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopSidebarCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererSidebarCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableSidebarV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableSidebarV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(({ slot }) => slot === 'sidebar_surface');
  if (definitions.length === 0) {
    return unavailableSidebarV2('desktop_renderer_sidebar_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableSidebarV2('desktop_renderer_sidebar_contribution_ambiguous');
  }
  const Surface = composition.resolveSidebarSurface(definitions[0]);
  if (Surface === null) {
    return unavailableSidebarV2('desktop_renderer_sidebar_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopRightSidebarCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererRightSidebarCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableRightSidebarV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableRightSidebarV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'right_sidebar_surface',
  );
  if (definitions.length === 0) {
    return unavailableRightSidebarV2('desktop_renderer_right_sidebar_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableRightSidebarV2('desktop_renderer_right_sidebar_contribution_ambiguous');
  }
  const Surface = composition.resolveRightSidebarSurface(definitions[0]);
  if (Surface === null) {
    return unavailableRightSidebarV2('desktop_renderer_right_sidebar_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopSettingsWindowCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererSettingsWindowCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableSettingsWindowV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableSettingsWindowV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'settings_window_surface',
  );
  if (definitions.length === 0) {
    return unavailableSettingsWindowV2(
      'desktop_renderer_settings_window_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableSettingsWindowV2(
      'desktop_renderer_settings_window_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveSettingsWindowSurface(definitions[0]);
  if (Surface === null) {
    return unavailableSettingsWindowV2('desktop_renderer_settings_window_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopSessionWorkspaceCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererSessionWorkspaceCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableSessionWorkspaceV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableSessionWorkspaceV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'session_workspace_surface',
  );
  if (definitions.length === 0) {
    return unavailableSessionWorkspaceV2(
      'desktop_renderer_session_workspace_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableSessionWorkspaceV2(
      'desktop_renderer_session_workspace_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveSessionWorkspaceSurface(definitions[0]);
  if (Surface === null) {
    return unavailableSessionWorkspaceV2(
      'desktop_renderer_session_workspace_module_unavailable',
    );
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopActivityInboxCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererActivityInboxCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableActivityInboxV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableActivityInboxV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'activity_inbox_surface',
  );
  if (definitions.length === 0) {
    return unavailableActivityInboxV2('desktop_renderer_activity_inbox_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableActivityInboxV2('desktop_renderer_activity_inbox_contribution_ambiguous');
  }
  const Surface = composition.resolveActivityInboxSurface(definitions[0]);
  if (Surface === null) {
    return unavailableActivityInboxV2('desktop_renderer_activity_inbox_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopMyWorkQueueCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererMyWorkQueueCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableMyWorkQueueV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableMyWorkQueueV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'my_work_queue_surface',
  );
  if (definitions.length === 0) {
    return unavailableMyWorkQueueV2('desktop_renderer_my_work_queue_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableMyWorkQueueV2('desktop_renderer_my_work_queue_contribution_ambiguous');
  }
  const Surface = composition.resolveMyWorkQueueSurface(definitions[0]);
  if (Surface === null) {
    return unavailableMyWorkQueueV2('desktop_renderer_my_work_queue_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopNewThreadComposerCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererNewThreadComposerCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableNewThreadComposerV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableNewThreadComposerV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'new_thread_composer_surface',
  );
  if (definitions.length === 0) {
    return unavailableNewThreadComposerV2(
      'desktop_renderer_new_thread_composer_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableNewThreadComposerV2(
      'desktop_renderer_new_thread_composer_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveNewThreadComposerSurface(definitions[0]);
  if (Surface === null) {
    return unavailableNewThreadComposerV2(
      'desktop_renderer_new_thread_composer_module_unavailable',
    );
  }
  return Object.freeze({ status: 'ready', Surface });
}

export function projectDesktopWorkspaceCollaborationCompositionV2(
  authority: Pick<DesktopRendererAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererWorkspaceCollaborationCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableWorkspaceCollaborationV2('desktop_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableWorkspaceCollaborationV2('desktop_renderer_generation_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'workspace_collaboration_surface',
  );
  if (definitions.length === 0) {
    return unavailableWorkspaceCollaborationV2(
      'desktop_renderer_workspace_collaboration_contribution_missing',
    );
  }
  if (definitions.length !== 1) {
    return unavailableWorkspaceCollaborationV2(
      'desktop_renderer_workspace_collaboration_contribution_ambiguous',
    );
  }
  const Surface = composition.resolveWorkspaceCollaborationSurface(definitions[0]);
  if (Surface === null) {
    return unavailableWorkspaceCollaborationV2(
      'desktop_renderer_workspace_collaboration_module_unavailable',
    );
  }
  return Object.freeze({ status: 'ready', Surface });
}

function unavailableAuthenticatedShellV2(
  reasonCode: Extract<
    DesktopRendererAuthenticatedShellCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererAuthenticatedShellCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableWorkbenchV2(
  reasonCode: Extract<
    DesktopRendererWorkbenchCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererWorkbenchCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableCommandPaletteV2(
  reasonCode: Extract<
    DesktopRendererCommandPaletteCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererCommandPaletteCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableWorkspaceCreateV2(
  reasonCode: Extract<
    DesktopRendererWorkspaceCreateCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererWorkspaceCreateCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableWorkspaceSettingsV2(
  reasonCode: Extract<
    DesktopRendererWorkspaceSettingsCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererWorkspaceSettingsCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableWorkbenchTabBarV2(
  reasonCode: Extract<
    DesktopRendererWorkbenchTabBarCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererWorkbenchTabBarCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableConversationV2(
  reasonCode: Extract<
    DesktopRendererConversationCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererConversationCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableSessionCanvasV2(
  reasonCode: Extract<
    DesktopRendererSessionCanvasCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererSessionCanvasCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableKeyboardShortcutsV2(
  reasonCode: Extract<
    DesktopRendererKeyboardShortcutsCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererKeyboardShortcutsCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableStatusBarV2(
  reasonCode: Extract<
    DesktopRendererStatusBarCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererStatusBarCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableTitlebarV2(
  reasonCode: Extract<
    DesktopRendererTitlebarCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererTitlebarCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableSidebarV2(
  reasonCode: Extract<
    DesktopRendererSidebarCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererSidebarCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableRightSidebarV2(
  reasonCode: Extract<
    DesktopRendererRightSidebarCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererRightSidebarCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableSettingsWindowV2(
  reasonCode: Extract<
    DesktopRendererSettingsWindowCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererSettingsWindowCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableSessionWorkspaceV2(
  reasonCode: Extract<
    DesktopRendererSessionWorkspaceCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererSessionWorkspaceCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableActivityInboxV2(
  reasonCode: Extract<
    DesktopRendererActivityInboxCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererActivityInboxCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableMyWorkQueueV2(
  reasonCode: Extract<
    DesktopRendererMyWorkQueueCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererMyWorkQueueCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableNewThreadComposerV2(
  reasonCode: Extract<
    DesktopRendererNewThreadComposerCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererNewThreadComposerCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}

function unavailableWorkspaceCollaborationV2(
  reasonCode: Extract<
    DesktopRendererWorkspaceCollaborationCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererWorkspaceCollaborationCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}
