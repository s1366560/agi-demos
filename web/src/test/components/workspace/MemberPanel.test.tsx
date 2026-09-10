import type { ReactNode } from 'react';

import { describe, expect, it, vi } from 'vitest';

import { App } from 'antd';

import { MemberPanel } from '@/components/workspace/MemberPanel';
import { render, screen } from '@/test/utils';

vi.mock('@/stores/workspace', () => ({
  useWorkspaceMembers: () => [],
  useWorkspaceAgents: () => [],
  useWorkspaceActions: () => ({
    bindAgent: vi.fn(),
    unbindAgent: vi.fn(),
  }),
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyPopconfirm: ({ children }: { children: ReactNode }) => children,
}));

vi.spyOn(App, 'useApp').mockReturnValue({
  message: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    loading: vi.fn(),
  },
} as unknown as ReturnType<typeof App.useApp>);

vi.mock('@/components/workspace/AddAgentModal', () => ({
  AddAgentModal: () => null,
}));

describe('MemberPanel', () => {
  it('marks member panel as a hosted non-authoritative projection', () => {
    render(<MemberPanel tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    const boundaryBadge = screen.getByText('workspace membership projection').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
  });
});
