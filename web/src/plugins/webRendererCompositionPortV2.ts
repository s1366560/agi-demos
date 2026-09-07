import { createContext, useContext, type ComponentType, type ReactNode } from 'react';

import type { WebUiSlotAuthorityStateV2 } from '../routes/v2/webUiSlotAuthorityStateV2';
import type { UiSlotDefinition } from '../types/pluginSlots';

export const WEB_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2 =
  'builtin:web-authenticated-shell-surface' as const;

export interface WebRendererAuthenticatedShellSurfacePropsV2 {
  readonly children: ReactNode;
}

export type WebRendererAuthenticatedShellSurfaceV2 =
  ComponentType<WebRendererAuthenticatedShellSurfacePropsV2>;

export interface WebRendererCompositionPortV2 {
  readonly resolveAuthenticatedShellSurface: (
    definition: UiSlotDefinition
  ) => WebRendererAuthenticatedShellSurfaceV2 | null;
}

export type WebRendererAuthenticatedShellCompositionV2 =
  | Readonly<{
      status: 'ready';
      Surface: WebRendererAuthenticatedShellSurfaceV2;
    }>
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'web_renderer_authenticated_shell_contribution_ambiguous'
        | 'web_renderer_authenticated_shell_contribution_missing'
        | 'web_renderer_authenticated_shell_module_unavailable'
        | 'web_renderer_composition_host_unavailable'
        | 'web_renderer_generation_disabled'
        | 'web_renderer_generation_unavailable';
    }>;

export const WebRendererCompositionContextV2 = createContext<
  WebRendererCompositionPortV2 | undefined
>(undefined);

export function useCurrentWebRendererCompositionV2(): WebRendererCompositionPortV2 | undefined {
  return useContext(WebRendererCompositionContextV2);
}

export function projectWebAuthenticatedShellCompositionV2(
  authority: Pick<WebUiSlotAuthorityStateV2, 'slotDefinitions' | 'status'>,
  composition: WebRendererCompositionPortV2 | undefined
): WebRendererAuthenticatedShellCompositionV2 {
  if (authority.status === 'loading') return Object.freeze({ status: 'loading' });
  if (authority.status === 'disabled') {
    return unavailableAuthenticatedShellV2('web_renderer_generation_disabled');
  }
  if (authority.status === 'unavailable') {
    return unavailableAuthenticatedShellV2('web_renderer_generation_unavailable');
  }
  if (composition === undefined) {
    return unavailableAuthenticatedShellV2('web_renderer_composition_host_unavailable');
  }
  const definitions = authority.slotDefinitions.filter(
    ({ slot }) => slot === 'authenticated_shell_surface'
  );
  const definition = definitions[0];
  if (definition === undefined) {
    return unavailableAuthenticatedShellV2('web_renderer_authenticated_shell_contribution_missing');
  }
  if (definitions.length !== 1) {
    return unavailableAuthenticatedShellV2(
      'web_renderer_authenticated_shell_contribution_ambiguous'
    );
  }
  const Surface = composition.resolveAuthenticatedShellSurface(definition);
  if (Surface === null) {
    return unavailableAuthenticatedShellV2('web_renderer_authenticated_shell_module_unavailable');
  }
  return Object.freeze({ status: 'ready', Surface });
}

function unavailableAuthenticatedShellV2(
  reasonCode: Extract<
    WebRendererAuthenticatedShellCompositionV2,
    Readonly<{ status: 'unavailable' }>
  >['reasonCode']
): WebRendererAuthenticatedShellCompositionV2 {
  return Object.freeze({ status: 'unavailable', reasonCode });
}
