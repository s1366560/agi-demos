import type { ReactNode } from 'react';

import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  WebRendererCompositionContextV2,
  type WebRendererCompositionPortV2,
} from '../../plugins/webRendererCompositionPortV2';
import { WebRendererAuthenticatedShellV2 } from '../../plugins/WebRendererAuthenticatedShellV2';
import { WebUiSlotAuthorityContextV2 } from '../../routes/v2/webUiSlotAuthorityStateV2';

import type { WebUiSlotAuthorityStateV2 } from '../../routes/v2/webUiSlotAuthorityStateV2';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const SLOT = Object.freeze({
  pluginId: 'builtin-shell',
  slot: 'authenticated_shell_surface' as const,
  id: 'authenticated-shell',
  contract: 'ui-builtin:web-authenticated-shell-surface',
  moduleRef: 'builtin:web-authenticated-shell-surface',
  permission: 'ui.authenticated-shell',
  sandbox: true,
});

const composition: WebRendererCompositionPortV2 = Object.freeze({
  resolveAuthenticatedShellSurface: () =>
    function TestShell({ children }: { readonly children: ReactNode }) {
      return <section data-testid="authenticated-shell">{children}</section>;
    },
});

function renderShell(state: WebUiSlotAuthorityStateV2) {
  return render(
    <WebRendererCompositionContextV2.Provider value={composition}>
      <WebUiSlotAuthorityContextV2.Provider value={state}>
        <MemoryRouter initialEntries={['/business']}>
          <Routes>
            <Route element={<WebRendererAuthenticatedShellV2 />}>
              <Route path="/business" element={<div data-testid="business-route">business</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </WebUiSlotAuthorityContextV2.Provider>
    </WebRendererCompositionContextV2.Provider>
  );
}

describe('WebRendererAuthenticatedShellV2', () => {
  it('renders a matched business route through the contributed shell surface', () => {
    renderShell({
      slotDefinitions: [SLOT],
      status: 'ready',
      uiSlotArtifactIds: ['web.ui-slots.authenticated-shell-surface.v1'],
    });

    expect(screen.getByTestId('authenticated-shell')).toContainElement(
      screen.getByTestId('business-route')
    );
  });

  it('fails closed when the required shell contribution is absent', () => {
    renderShell({ slotDefinitions: [], status: 'ready', uiSlotArtifactIds: [] });

    expect(screen.getByRole('alert')).toHaveAttribute(
      'data-reason-code',
      'web_renderer_authenticated_shell_contribution_missing'
    );
    expect(screen.queryByTestId('business-route')).not.toBeInTheDocument();
  });

  it('keeps the business route hidden while the generation is loading', () => {
    renderShell({ slotDefinitions: [], status: 'loading', uiSlotArtifactIds: [] });

    expect(screen.getByRole('status')).toHaveTextContent('common.loading');
    expect(screen.queryByTestId('business-route')).not.toBeInTheDocument();
  });
});
