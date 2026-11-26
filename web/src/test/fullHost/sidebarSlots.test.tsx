import { act, fireEvent, renderHook, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Navigate } from 'react-router-dom';
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
      inputs: { cursor: 'cursor' },
      collection: 'entries',
      fields: { id: 'uuid', label: 'subject', hidden: 'hidden' },
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
    // A command that does not page has returned all of its rows.
    expect(await result.current('rows', {}, signal)).toEqual({
      rows: [{ id: 'n1', label: 'My notebook' }],
      count: 1,
      hasMore: false,
      cursor: null,
    });
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
    expect(
      rowNavigation(undefined, 'tenant', null).match('/tenant/tenant/agent-workspace')
    ).toBeNull();
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

  it('keeps derived rows for the count and reads the next page when asked', async () => {
    send.mockImplementation(async (_path, { body }) =>
      body.payload.cursor
        ? { entries: [{ uuid: 'n2', subject: 'Second' }], has_more: false, cursor: null }
        : {
            entries: [
              { uuid: 'n1', subject: 'First' },
              { uuid: 'd1', subject: 'Workspace Worker - derived', hidden: true },
            ],
            has_more: true,
            cursor: 'next-page',
          }
    );
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MemoryRouter>
        <SignedSidebarProvider>{children}</SignedSidebarProvider>
      </MemoryRouter>
    );
    const { result } = renderHook(() => useSignedSidebar(), { wrapper });
    await waitFor(() =>
      expect(result.current.conversations.map((row) => row.id)).toEqual(['n1', 'd1'])
    );
    // The derived row is counted, as the original workbench counts it, and the
    // view leaves it out of the list.
    expect(result.current.conversations[1].slot).toEqual({ active: false, hidden: true });
    expect(result.current.hasMoreConversations).toBe(true);

    act(() => void result.current.loadMoreConversations('project-a'));
    await waitFor(() =>
      expect(result.current.conversations.map((row) => row.id)).toEqual(['n1', 'd1', 'n2'])
    );
    expect(send).toHaveBeenLastCalledWith(
      expect.stringContaining('/acme.notebooks/commands'),
      expect.objectContaining({
        body: expect.objectContaining({
          command_id: 'enumerate',
          payload: { cursor: 'next-page' },
        }),
      })
    );
    expect(result.current.hasMoreConversations).toBe(false);
    // Nothing follows, so asking again reads nothing.
    await result.current.loadMoreConversations('project-a');
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('lists a conversation the page opened by its address', async () => {
    let created = false;
    send.mockImplementation(async () => ({
      entries: [
        { uuid: 'n1', subject: 'First' },
        ...(created ? [{ uuid: 'n2', subject: 'Just created' }] : []),
      ],
    }));
    const router = { go: '' };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MemoryRouter initialEntries={['/notebooks']}>
        {router.go && <Navigate to={router.go} />}
        <SignedSidebarProvider>{children}</SignedSidebarProvider>
      </MemoryRouter>
    );
    const { result, rerender } = renderHook(() => useSignedSidebar(), { wrapper });
    await waitFor(() => expect(result.current.conversations.map((row) => row.id)).toEqual(['n1']));
    // The page names a conversation in the address as soon as it has created it.
    created = true;
    router.go = '/notebooks/n2';
    rerender();
    await waitFor(() =>
      expect(result.current.conversations.map((row) => row.id)).toEqual(['n1', 'n2'])
    );
    // The rows are read again without showing that they are, and only once.
    expect(result.current.conversationsLoading).toBe(false);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('counts a derived row in the original sidebar without listing it', async () => {
    send.mockResolvedValue({
      entries: [
        { uuid: 'n1', subject: 'Listed notebook' },
        { uuid: 'd1', subject: 'Workspace Worker - derived', hidden: true },
      ],
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
    expect(await screen.findByRole('link', { name: /Listed notebook/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /derived/ })).toBeNull();
    expect(screen.getByText(/^(2 conversations|2 个对话)$/)).toBeInTheDocument();
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
