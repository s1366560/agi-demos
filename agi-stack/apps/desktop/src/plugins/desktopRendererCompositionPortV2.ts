import type { ComponentType } from 'react';

import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteRegistry } from '../features/navigation/desktopRouteRegistry';
import type { DesktopActivityInboxSurfacePropsV2 } from './DesktopActivityInboxSurfaceV2';
import type { DesktopAuthenticatedShellViewModelV2 } from './DesktopAuthenticatedShellSurfaceV2';
import type { DesktopMyWorkQueueSurfacePropsV2 } from './DesktopMyWorkQueueSurfaceV2';
import type { DesktopNewThreadComposerSurfacePropsV2 } from './DesktopNewThreadComposerSurfaceV2';
import type { DesktopSessionCanvasSurfacePropsV2 } from './DesktopSessionCanvasSurfaceV2';
import type { DesktopWorkspaceCollaborationSurfacePropsV2 } from './DesktopWorkspaceCollaborationSurfaceV2';
import type { DesktopWorkbenchSurfaceViewModelV2 } from './DesktopWorkbenchSurfaceV2';
import type { DesktopRendererAuthorityStateV2 } from './desktopRendererAuthorityStateV2';
import type { UiSlotDefinition } from './uiSlotRegistry';

export const DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-authenticated-shell-surface' as const;
export const DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-session-canvas-surface' as const;
export const DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2 = 'builtin:desktop-workbench-surface' as const;
export const DESKTOP_ACTIVITY_INBOX_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-activity-inbox-surface' as const;
export const DESKTOP_MY_WORK_QUEUE_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-my-work-queue-surface' as const;
export const DESKTOP_NEW_THREAD_COMPOSER_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-new-thread-composer-surface' as const;
export const DESKTOP_WORKSPACE_COLLABORATION_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-workspace-collaboration-surface' as const;

export type DesktopRendererActivityInboxSurfaceV2 =
  ComponentType<DesktopActivityInboxSurfacePropsV2>;
export type DesktopRendererMyWorkQueueSurfaceV2 =
  ComponentType<DesktopMyWorkQueueSurfacePropsV2>;
export type DesktopRendererNewThreadComposerSurfaceV2 =
  ComponentType<DesktopNewThreadComposerSurfacePropsV2>;
export type DesktopRendererWorkspaceCollaborationSurfaceV2 =
  ComponentType<DesktopWorkspaceCollaborationSurfacePropsV2>;

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
  readonly resolveMyWorkQueueSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererMyWorkQueueSurfaceV2 | null;
  readonly resolveNewThreadComposerSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererNewThreadComposerSurfaceV2 | null;
  readonly resolveSessionCanvasSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererSessionCanvasSurfaceV2 | null;
  readonly resolveWorkspaceCollaborationSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererWorkspaceCollaborationSurfaceV2 | null;
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

function unavailableSessionCanvasV2(
  reasonCode: Extract<
    DesktopRendererSessionCanvasCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode'],
): DesktopRendererSessionCanvasCompositionV2 {
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
