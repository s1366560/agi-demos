import { WebAuthenticatedShellSurfaceV2 } from './WebAuthenticatedShellSurfaceV2';
import {
  WEB_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2,
  type WebRendererCompositionPortV2,
} from './webRendererCompositionPortV2';

import type { UiSlotDefinition } from '../types/pluginSlots';

export function createWebRendererAppCompositionPortV2(): WebRendererCompositionPortV2 {
  return Object.freeze({
    resolveAuthenticatedShellSurface: (definition: UiSlotDefinition) =>
      validAuthenticatedShellDefinitionV2(definition) ? WebAuthenticatedShellSurfaceV2 : null,
  });
}

function validAuthenticatedShellDefinitionV2(definition: UiSlotDefinition): boolean {
  return (
    definition.pluginId === 'builtin-shell' &&
    definition.slot === 'authenticated_shell_surface' &&
    definition.id === 'authenticated-shell' &&
    definition.contract === 'ui-builtin:web-authenticated-shell-surface' &&
    definition.moduleRef === WEB_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2 &&
    definition.permission === 'ui.authenticated-shell' &&
    definition.sandbox
  );
}
