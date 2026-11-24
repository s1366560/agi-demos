import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getDataSpy, resolvePathSpy } = vi.hoisted(() => ({
  getDataSpy: vi.fn(),
  resolvePathSpy: vi.fn((path: string) => (path.startsWith('/') ? path : `/${path}`)),
}));

vi.mock('@business/agent/ui/web/canvas/a2uiInternals', async () => {
  const actual = await vi.importActual<typeof import('@business/agent/ui/web/canvas/a2uiInternals')>(
    '@business/agent/ui/web/canvas/a2uiInternals'
  );
  return {
    ...actual,
    useA2UIActions: () => ({
      getData: getDataSpy,
      resolvePath: resolvePathSpy,
    }),
    useA2UIState: () => ({ version: 1 }),
  };
});

import { A2UITable } from '@/components/agent/canvas/A2UITable';

describe('A2UITable', () => {
  const node = {
    id: 'table-1',
    type: 'Table',
    dataContextPath: '/',
    properties: {
      caption: { literalString: 'Members' },
      columns: [{ header: { literalString: 'Name' } }, { header: { literalString: 'Status' } }],
      rows: [
        { key: 'row-1', cells: [{ literalString: 'Alice' }, { literalString: 'Active' }] },
        { key: 'row-2', cells: [{ literalString: 'Bob' }, { path: '/members/1/status' }] },
      ],
    },
  };

  beforeEach(() => {
    getDataSpy.mockReset();
    resolvePathSpy.mockClear();
  });

  it('renders table headers and bound cell values', () => {
    getDataSpy.mockImplementation((_node: unknown, path: string) =>
      path === '/members/1/status' ? 'Pending' : undefined
    );

    render(<A2UITable node={node} surfaceId="surface-1" />);

    expect(screen.getByText('Members')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Status' })).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });
});
