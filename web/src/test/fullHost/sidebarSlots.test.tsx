import { renderHook, fireEvent, within } from '@testing-library/react';
import { render, screen, waitFor } from '../utils';
import { SignedSidebarProvider, useSignedSidebar } from '../../fullHost/sidebarData';
import { TenantSidebarView } from '../../components/layout/TenantSidebarView';
import { describe, expect, it, vi } from 'vitest';
import { ownerFor, rowNavigation, type SlotOwner } from '../../fullHost/sidebarSlots';
import { useSidebarSlot } from '../../fullHost/useSidebarSlot';
import type { MarketplaceTransport } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/client';

const owner: SlotOwner = {
  plugin: 'acme.notebooks',
  digest: 'first',
  projectId: 'project-a',
  label: 'Notebooks',
  id: 'notes',
  path: '/notes',
  commands: ['enumerate', 'retitle'],
  routes: ['/notebooks', '/notebooks/:note'],
  sidebar: {
    rows: {
      command: 'enumerate',
      collection: 'entries',
      fields: { id: 'uuid', label: 'subject' },
      route: '/notebooks',
      row_route: '/notebooks/:note',
      row_param: 'note',
    },
    rename: { command: 'retitle', inputs: { notebook_key: 'id', new_subject: 'label' } },
  },
};
const send = vi.fn();
vi.mock('../../fullHost/navigation', () => ({
  useFullNavigation: () => ({ tenant: 'tenant', project: 'project-a', items: [owner] }),
}));
vi.mock('../../projectPackages/useWebPackageSession', () => ({
  useWebPackageSession: () => ({ transport: send }),
}));
const project = { id: 'project-a', name: 'Books', tenant_id: 'tenant' };
const projectState = {
  projects: [project],
  currentProject: project,
  listProjects: vi.fn(),
  setCurrentProject: vi.fn(),
};
vi.mock('../../stores/project', () => ({
  useProjectStore: (select: (state: typeof projectState) => unknown) => select(projectState),
}));
const signal = new AbortController().signal;
describe('signed sidebar contributions', () => {
  it('projects a differently named provider into the original row and action controls', async () => {
    const send = vi.fn().mockResolvedValue({ entries: [{ uuid: 'n1', subject: 'My notebook' }] });
    expect(ownerFor([owner], owner.projectId!, 'rows')).toBe(owner);
    expect(ownerFor([owner], 'other', 'rows')).toBeUndefined();
    expect(ownerFor([{ ...owner, commands: [] }], owner.projectId!, 'rows')).toBeUndefined();
    const { result } = renderHook(() => useSidebarSlot('tenant', 'project-a', owner, send));
    expect((await result.current('rows', {}, signal)).rows).toEqual([
      { id: 'n1', label: 'My notebook' },
    ]);
    await result.current('rename', { id: 'n1', label: 'Next' });
    expect(send).toHaveBeenLastCalledWith(
      expect.stringContaining('/acme.notebooks/commands'),
      expect.objectContaining({
        body: {
          tenant_id: 'tenant',
          project_id: 'project-a',
          expected_digest: 'first',
          command_id: 'retitle',
          payload: { notebook_key: 'n1', new_subject: 'Next' },
        },
      })
    );
    const other = { ...owner, plugin: 'other.notebook', routes: ['/other/:id'] };
    expect(ownerFor([other, owner], 'project-a', 'rows', '/notebooks/n1')).toBe(owner);
    expect(rowNavigation(undefined, 'tenant', null).match('/tenant/tenant/agent-workspace')).toBeNull();
    const nav = rowNavigation(owner, 'tenant', 'project-a');
    expect(nav.link('n1')).toContain('/notebooks/n1?');
    expect(nav.link('a b')).toContain('/notebooks/a%20b?');
    expect(nav.link('..')).toBeNull();
    expect(nav.match('/notebooks/n1')).toEqual({ active: true, id: 'n1' });
  });

  it('renders contributed labels and routes in the original sidebar and invokes the selected row action', async () => {
    let label = 'Workspace Worker - notebook title';
    send.mockImplementation(async (_path, { body }) => {
      if (body.command_id === 'retitle') label = body.payload.new_subject;
      return { entries: [{ uuid: 'n1', subject: label }] };
    });
    render(
      <SignedSidebarProvider>
        <TenantSidebarView
          mobile
          tenantId="tenant"
          useSidebarData={useSignedSidebar}
          useNavigationItems={() => []}
          NavigationSlot={() => null}
        />
      </SignedSidebarProvider>,
      { route: '/notebooks?projectId=project-a' }
    );
    const row = await screen.findByRole('link', { name: /Workspace Worker - notebook title/ });
    expect(row.getAttribute('href')).toContain('/notebooks/n1?');
    fireEvent.click(within(row).getByRole('button', { name: /rename|重命名/i }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Updated title' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /rename|重命名/i }));
    await waitFor(() => expect(row).toHaveTextContent('Updated title'));
  });

  it.each(['tenant', 'project', 'release', 'account'])(
    'drops outstanding results after changing %s',
    async (change) => {
      let finish!: (value: unknown) => void;
      const send = vi.fn(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          })
      ) as MarketplaceTransport;
      const initialProps = { tenant: 't', project: 'project-a', owner, transport: send };
      const hook = renderHook((p) => useSidebarSlot(p.tenant, p.project, p.owner, p.transport), {
        initialProps,
      });
      const previous = hook.result.current;
      const pending = previous('rows', {});
      hook.rerender({
        ...initialProps,
        ...(change === 'tenant' ? { tenant: 'new-tenant' } : {}),
        ...(change === 'project' ? { project: 'next' } : {}),
        ...(change === 'release' ? { owner: { ...owner, digest: 'next' } } : {}),
        ...(change === 'account' ? { transport: vi.fn() as MarketplaceTransport } : {}),
      });
      finish({ entries: [{ uuid: 'stale', subject: 'Old tenant' }] });
      await expect(pending).rejects.toThrow();
      expect(() => previous('rename', { id: 'stale', label: 'Bad' })).toThrow('page_scope_expired');
    }
  );
});
