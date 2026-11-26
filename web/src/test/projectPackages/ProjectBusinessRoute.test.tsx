import type { ReactNode } from 'react';

import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProjectBusinessRoute } from '../../projectPackages/ProjectBusinessRoute';

const routeState = vi.hoisted(() => ({ available: true }));
vi.mock('@/utils/tokenResolver', () => ({
  getAuthToken: () => 'example',
  subscribeCloudIdentity: () => () => {},
}));
vi.mock('../../projectPackages/useWebPackageSession', () => ({
  useWebPackageSession: () => ({}),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('../../../../agi-stack/packages/plugin-marketplace-ui/src/RichPackagePages', () => ({
  RichPackagePages: ({
    backToMarket,
    pageMenu,
    diagnostics,
  }: {
    backToMarket?: ReactNode;
    pageMenu?: boolean;
    diagnostics?: boolean;
  }) => (
    <section
      data-testid="signed-page"
      data-page-menu={String(pageMenu)}
      data-diagnostics={String(diagnostics)}
    >
      {backToMarket}
    </section>
  ),
}));

function ExistingRoute() {
  const { pathname, search, hash } = useLocation();
  return <output data-testid="existing-route">{pathname + search + hash}</output>;
}
const url = '/tenant/t/project/p/workspaces/new?from=bookmark&businessPackage=workspace#form';
function mount(address = url) {
  render(
    <MemoryRouter initialEntries={[address]}>
      <ProjectBusinessRoute matchesFullRoute={() => routeState.available}>
        <ExistingRoute />
      </ProjectBusinessRoute>
    </MemoryRouter>
  );
}
describe('ProjectBusinessRoute', () => {
  beforeEach(() => {
    routeState.available = true;
  });

  it('opens the authorized full route on the same path and retains bookmark state', () => {
    mount();
    expect(screen.getByTestId('signed-page')).toBeInTheDocument();
    const full = screen.getByRole('link', { name: 'tenant.pluginHub.openFullWorkbench' });
    const target = url.replace('#form', '&workbench=full#form');
    expect(full).toHaveAttribute('href', target);
    fireEvent.click(full);
    expect(screen.getByTestId('existing-route')).toHaveTextContent(target);
    expect(screen.queryByTestId('signed-page')).not.toBeInTheDocument();
  });

  it('keeps signed-only pages in the package even if the bookmark requests a full view', () => {
    routeState.available = false;
    mount(url.replace('#form', '&workbench=full#form'));
    expect(screen.getByTestId('signed-page')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'tenant.pluginHub.openFullWorkbench' })).toBeNull();
    expect(screen.queryByTestId('existing-route')).toBeNull();
  });

  it('leaves page navigation to the workbench shell', () => {
    render(
      <MemoryRouter initialEntries={[url]}>
        <ProjectBusinessRoute insideWorkbench matchesFullRoute={() => false}>
          <ExistingRoute />
        </ProjectBusinessRoute>
      </MemoryRouter>
    );

    expect(screen.getByTestId('signed-page')).toHaveAttribute('data-page-menu', 'false');
    expect(screen.getByTestId('signed-page')).toHaveAttribute('data-diagnostics', 'false');
  });

  it('keeps the page menu when a marketplace review opens a workbench page', () => {
    const [pathname, search] = url.split('#')[0].split('?');
    render(
      <MemoryRouter
        initialEntries={[
          { pathname, search: `?${search}`, hash: '#form', state: { fromPackageMarket: true } },
        ]}
      >
        <ProjectBusinessRoute insideWorkbench matchesFullRoute={() => false}>
          <ExistingRoute />
        </ProjectBusinessRoute>
      </MemoryRouter>
    );

    expect(screen.getByTestId('signed-page')).toHaveAttribute('data-page-menu', 'true');
  });

  it('offers the page menu outside the workbench and shows diagnostics only on request', () => {
    mount(url.replace('?from=bookmark', '?from=bookmark&diagnostics=1'));

    expect(screen.getByTestId('signed-page')).toHaveAttribute('data-page-menu', 'true');
    expect(screen.getByTestId('signed-page')).toHaveAttribute('data-diagnostics', 'true');
  });
});
