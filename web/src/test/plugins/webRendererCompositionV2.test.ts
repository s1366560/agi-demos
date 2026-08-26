import type { ComponentType, ReactNode } from 'react';

import { describe, expect, it, vi } from 'vitest';

import {
  projectWebAuthenticatedShellCompositionV2,
  type WebRendererCompositionPortV2,
} from '../../plugins/webRendererCompositionPortV2';

import type { UiSlotDefinition } from '../../types/pluginSlots';

const AUTHENTICATED_SHELL_SLOT: UiSlotDefinition = Object.freeze({
  pluginId: 'builtin-shell',
  slot: 'authenticated_shell_surface',
  id: 'authenticated-shell',
  contract: 'ui-builtin:web-authenticated-shell-surface',
  moduleRef: 'builtin:web-authenticated-shell-surface',
  permission: 'ui.authenticated-shell',
  sandbox: true,
});

const Surface = (({ children }: { readonly children: ReactNode }) => children) as ComponentType<{
  readonly children: ReactNode;
}>;

function composition(
  resolveAuthenticatedShellSurface: WebRendererCompositionPortV2['resolveAuthenticatedShellSurface'] = () =>
    Surface
): WebRendererCompositionPortV2 {
  return { resolveAuthenticatedShellSurface };
}

describe('web renderer authenticated shell composition v2', () => {
  it.each([
    ['loading', 'loading', undefined],
    ['disabled', 'unavailable', 'web_renderer_generation_disabled'],
    ['unavailable', 'unavailable', 'web_renderer_generation_unavailable'],
  ] as const)('projects %s authority without inventing a shell', (status, expected, reasonCode) => {
    expect(
      projectWebAuthenticatedShellCompositionV2({ slotDefinitions: [], status }, composition())
    ).toEqual(reasonCode === undefined ? { status: expected } : { status: expected, reasonCode });
  });

  it('fails closed when the authenticated shell contribution is missing or ambiguous', () => {
    expect(
      projectWebAuthenticatedShellCompositionV2(
        { slotDefinitions: [], status: 'ready' },
        composition()
      )
    ).toEqual({
      status: 'unavailable',
      reasonCode: 'web_renderer_authenticated_shell_contribution_missing',
    });
    expect(
      projectWebAuthenticatedShellCompositionV2(
        {
          slotDefinitions: [
            AUTHENTICATED_SHELL_SLOT,
            { ...AUTHENTICATED_SHELL_SLOT, id: 'other-shell' },
          ],
          status: 'ready',
        },
        composition()
      )
    ).toEqual({
      status: 'unavailable',
      reasonCode: 'web_renderer_authenticated_shell_contribution_ambiguous',
    });
  });

  it('fails closed when the host cannot resolve the declared builtin module', () => {
    const resolve = vi.fn(() => null);

    expect(
      projectWebAuthenticatedShellCompositionV2(
        { slotDefinitions: [AUTHENTICATED_SHELL_SLOT], status: 'ready' },
        composition(resolve)
      )
    ).toEqual({
      status: 'unavailable',
      reasonCode: 'web_renderer_authenticated_shell_module_unavailable',
    });
    expect(resolve).toHaveBeenCalledWith(AUTHENTICATED_SHELL_SLOT);
  });

  it('returns only the host-resolved surface for the exact active contribution', () => {
    expect(
      projectWebAuthenticatedShellCompositionV2(
        { slotDefinitions: [AUTHENTICATED_SHELL_SLOT], status: 'ready' },
        composition()
      )
    ).toEqual({ status: 'ready', Surface });
  });
});
