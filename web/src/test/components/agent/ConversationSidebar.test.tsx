import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ConversationSidebar } from '@/components/agent/ConversationSidebar';
import type { Conversation } from '@/types/agent';

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyButton: ({ children, icon, type: _antdType, ...props }: any) => (
    <button type="button" {...props}>
      {icon}
      {children}
    </button>
  ),
  LazyTooltip: ({ children }: any) => <>{children}</>,
  LazyDropdown: () => null,
  LazyModal: ({ children, open }: any) => (open ? <div role="dialog">{children}</div> : null),
  LazyInput: (props: any) => <input {...props} />,
  LazyCheckbox: ({ children, ...props }: any) => (
    <label>
      <input type="checkbox" {...props} />
      {children}
    </label>
  ),
  LazyPopover: () => null,
}));

const conversations: Conversation[] = [
  {
    id: 'conv-1',
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    title: 'Implement backend purchase API',
    status: 'active',
    message_count: 3,
    created_at: '2026-05-21T00:00:00',
  },
];

function renderSidebar(collapsed: boolean) {
  return render(
    <ConversationSidebar
      conversations={conversations}
      activeId="conv-1"
      onSelect={vi.fn()}
      onNew={vi.fn()}
      onDelete={vi.fn()}
      collapsed={collapsed}
      onToggleCollapse={vi.fn()}
    />
  );
}

describe('ConversationSidebar', () => {
  it('renders conversation entries when expanded', () => {
    renderSidebar(false);

    expect(screen.getByText('Implement backend purchase API')).toBeInTheDocument();
  });

  it('does not render conversation icon entries when collapsed', () => {
    renderSidebar(true);

    expect(screen.queryByText('Implement backend purchase API')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument();
  });
});
