import type { ComponentType } from 'react';

import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteRegistry } from '../features/navigation/desktopRouteRegistry';
import type { DesktopAuthenticatedShellViewModelV2 } from './DesktopAuthenticatedShellSurfaceV2';
import type { DesktopSessionCanvasSurfacePropsV2 } from './DesktopSessionCanvasSurfaceV2';
import type { DesktopWorkbenchSurfaceViewModelV2 } from './DesktopWorkbenchSurfaceV2';
import type { DesktopRendererAuthorityStateV2 } from './desktopRendererAuthorityStateV2';
import type { UiSlotDefinition } from './uiSlotRegistry';

export const DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-authenticated-shell-surface' as const;
export const DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2 =
  'builtin:desktop-session-canvas-surface' as const;
export const DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2 = 'builtin:desktop-workbench-surface' as const;

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
  readonly resolveAuthenticatedShellSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererAuthenticatedShellSurfaceV2 | null;
  readonly resolveSessionCanvasSurface: (
    definition: UiSlotDefinition,
  ) => DesktopRendererSessionCanvasSurfaceV2 | null;
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
