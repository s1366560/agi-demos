import { describe, expect, it, vi } from 'vitest';

import { CollaborationOverviewTab } from '@/components/blackboard/tabs/CollaborationOverviewTab';
import { render, screen } from '@/test/utils';

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: (selector: (state: unknown) => unknown) =>
    selector({
      chatMessages: [],
      loadChatMessages: vi.fn(),
    }),
}));

describe('CollaborationOverviewTab', () => {
  it('marks collaboration chat overview as a hosted non-authoritative projection', () => {
    render(
      <CollaborationOverviewTab
        tenantId="t-1"
        projectId="p-1"
        workspaceId="ws-1"
        agents={[]}
      />
    );

    const boundaryBadge = screen.getByText('blackboard.collaborationSurfaceHint').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
  });
});
