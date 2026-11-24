import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { a2uiState, getDataSpy, resolvePathSpy } = vi.hoisted(() => ({
  a2uiState: (() => {
    const listeners = new Set<() => void>();
    return {
      version: 1,
      publish(nextVersion: number) {
        this.version = nextVersion;
        listeners.forEach((listener) => listener());
      },
      subscribe(listener: () => void) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    };
  })(),
  getDataSpy: vi.fn(),
  resolvePathSpy: vi.fn((path: string) => (path.startsWith('/') ? path : `/${path}`)),
}));

vi.mock('@business/agent/ui/web/canvas/a2uiInternals', async () => {
  const actual = await vi.importActual<typeof import('@business/agent/ui/web/canvas/a2uiInternals')>(
    '@business/agent/ui/web/canvas/a2uiInternals'
  );
  const React = await vi.importActual<typeof import('react')>('react');
  return {
    ...actual,
    useA2UIActions: () => ({
      getData: getDataSpy,
      resolvePath: resolvePathSpy,
    }),
    useA2UIState: () => ({
      version: React.useSyncExternalStore(a2uiState.subscribe, () => a2uiState.version),
    }),
  };
});

import { A2UIProgress } from '@/components/agent/canvas/A2UIProgress';

describe('A2UIProgress', () => {
  const node = {
    id: 'progress-1',
    type: 'Progress',
    dataContextPath: '/',
    properties: {
      label: { literalString: 'Completion' },
      value: { path: '/progress/current', literalNumber: 10 },
      max: { literalNumber: 40 },
      tone: 'success',
    },
  };

  beforeEach(() => {
    a2uiState.version = 1;
    getDataSpy.mockReset();
    resolvePathSpy.mockClear();
  });

  it('renders the current percentage from bound progress data', () => {
    getDataSpy.mockReturnValue(20);

    render(<A2UIProgress node={node} surfaceId="surface-1" />);

    expect(screen.getByText('Completion')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Completion' })).toHaveAttribute(
      'aria-valuenow',
      '20'
    );
  });

  it('refreshes when the bound progress data changes', async () => {
    let currentValue = 10;
    getDataSpy.mockImplementation(() => currentValue);

    render(<A2UIProgress node={node} surfaceId="surface-1" />);
    expect(screen.getByText('25%')).toBeInTheDocument();

    act(() => {
      currentValue = 30;
      a2uiState.publish(a2uiState.version + 1);
    });

    await waitFor(() => {
      expect(screen.getByText('75%')).toBeInTheDocument();
    });
  });

  it('uses a generic accessible name when no visible label is rendered', () => {
    getDataSpy.mockReturnValue(20);

    render(
      <A2UIProgress
        node={{
          ...node,
          properties: {
            ...node.properties,
            label: undefined,
            showValue: false,
          },
        }}
        surfaceId="surface-1"
      />
    );

    expect(screen.getByRole('progressbar', { name: 'Progress' })).toBeInTheDocument();
  });
});
