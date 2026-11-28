import type { ReactElement, ReactNode } from 'react';

import { QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const renderSpy = vi.fn();
const createRootSpy = vi.fn(() => ({
  render: renderSpy,
}));

vi.mock('react-dom/client', () => ({
  createRoot: createRootSpy,
  default: {
    createRoot: createRootSpy,
  },
}));

vi.mock('../components/common/AppInitializer', () => ({
  AppInitializer: ({ children }: { children: ReactNode }) => children,
}));

function findElementByType(node: ReactNode, target: unknown): ReactElement | null {
  if (!node || typeof node !== 'object') {
    return null;
  }

  if (Array.isArray(node)) {
    for (const child of node) {
      const match = findElementByType(child, target);
      if (match) {
        return match;
      }
    }
    return null;
  }

  if (!('type' in node)) {
    return null;
  }

  const element = node as ReactElement<{ children?: ReactNode }>;
  if (element.type === target) {
    return element;
  }

  return findElementByType(element.props.children, target);
}

describe('main entrypoint', () => {
  beforeEach(() => {
    createRootSpy.mockClear();
    renderSpy.mockClear();
    vi.resetModules();
    document.body.innerHTML = '<div id="root"></div>';
  });

  it('wraps the application with the shared QueryClientProvider', async () => {
    await import('../fullHost/main');
    const { queryClient } = await import('../services/client/queryClient');

    expect(createRootSpy).toHaveBeenCalledWith(document.getElementById('root'));
    const [appTree] = renderSpy.mock.calls[0] ?? [];
    const provider = findElementByType(appTree, QueryClientProvider);

    expect(provider).not.toBeNull();
    expect(provider?.props.client).toBe(queryClient);
  });
});
