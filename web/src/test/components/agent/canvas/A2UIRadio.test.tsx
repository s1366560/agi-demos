import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { a2uiState, dispatchSpy, getDataSpy, resolvePathSpy, setDataSpy } = vi.hoisted(() => ({
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
  dispatchSpy: vi.fn(),
  getDataSpy: vi.fn(),
  resolvePathSpy: vi.fn((path: string) => (path.startsWith('/') ? path : `/${path}`)),
  setDataSpy: vi.fn(),
}));

vi.mock('@business/agent/ui/web/canvas/a2uiInternals', async () => {
  const actual = await vi.importActual<typeof import('@business/agent/ui/web/canvas/a2uiInternals')>(
    '@business/agent/ui/web/canvas/a2uiInternals'
  );
  const React = await vi.importActual<typeof import('react')>('react');
  return {
    ...actual,
    useA2UIActions: () => ({
      setData: setDataSpy,
      getData: getDataSpy,
      resolvePath: resolvePathSpy,
      dispatch: dispatchSpy,
    }),
    useA2UIState: () => ({
      version: React.useSyncExternalStore(a2uiState.subscribe, () => a2uiState.version),
    }),
  };
});

import { ensureMemStackA2UIRegistry } from '@/components/agent/canvas/A2UIMemStackRegistry';
import { A2UIRadio } from '@/components/agent/canvas/A2UIRadio';
import { ComponentRegistry } from '@business/agent/ui/web/canvas/a2uiInternals';

describe('A2UIRadio', () => {
  const node = {
    id: 'radio-1',
    type: 'Radio',
    dataContextPath: '/',
    properties: {
      description: { literalString: 'Plan' },
      options: [
        { label: { literalString: 'Starter' }, value: 'starter' },
        { label: { literalString: 'Pro' }, value: 'pro' },
      ],
      value: { path: '/form/plan', literalString: 'starter' },
    },
  };

  beforeEach(() => {
    a2uiState.version = 1;
    dispatchSpy.mockReset();
    getDataSpy.mockReset();
    resolvePathSpy.mockClear();
    setDataSpy.mockReset();
  });

  it('renders the current selection from the bound data path', () => {
    getDataSpy.mockReturnValue('starter');

    render(<A2UIRadio node={node} surfaceId="surface-1" />);

    expect(screen.getByRole('radiogroup', { name: 'Plan' })).toBeInTheDocument();
    expect(screen.getByLabelText('Starter')).toBeChecked();
    expect(screen.getByLabelText('Pro')).not.toBeChecked();
  });

  it('falls back to the literal default while keeping the path binding intact', () => {
    getDataSpy.mockReturnValue(undefined);

    render(<A2UIRadio node={node} surfaceId="surface-1" />);
    expect(screen.getByLabelText('Starter')).toBeChecked();
    fireEvent.click(screen.getByLabelText('Pro'));

    expect(setDataSpy).toHaveBeenCalledWith(node, '/form/plan', 'pro', 'surface-1');
  });

  it('writes a scalar selected value back to the bound data path', () => {
    getDataSpy.mockReturnValue('starter');

    render(<A2UIRadio node={node} surfaceId="surface-1" />);
    fireEvent.click(screen.getByLabelText('Pro'));

    expect(setDataSpy).toHaveBeenCalledWith(node, '/form/plan', 'pro', 'surface-1');
  });

  it('uses a human-readable fallback name when no description is provided', () => {
    getDataSpy.mockReturnValue('starter');

    render(
      <A2UIRadio
        node={{
          ...node,
          properties: {
            ...node.properties,
            description: undefined,
          },
        }}
        surfaceId="surface-1"
      />
    );

    expect(screen.getByRole('radiogroup', { name: 'Selection options' })).toBeInTheDocument();
  });

  it('refreshes the checked option when the bound A2UI data changes', async () => {
    let currentValue = 'starter';
    getDataSpy.mockImplementation(() => currentValue);

    render(<A2UIRadio node={node} surfaceId="surface-1" />);
    expect(screen.getByLabelText('Starter')).toBeChecked();

    act(() => {
      currentValue = 'pro';
      a2uiState.publish(a2uiState.version + 1);
    });

    await waitFor(() => {
      expect(screen.getByLabelText('Pro')).toBeChecked();
    });
  });

  it('registers custom MemStack components in the shared registry', () => {
    ensureMemStackA2UIRegistry();

    expect(ComponentRegistry.getInstance().has('Radio')).toBe(true);
    expect(ComponentRegistry.getInstance().has('Progress')).toBe(true);
    expect(ComponentRegistry.getInstance().has('Table')).toBe(true);
  });
});
