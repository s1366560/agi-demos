import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { EmptyState } from '@/components/agent/EmptyState';

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyButton: ({
    children,
    className,
    icon,
    onClick,
  }: {
    children: ReactNode;
    className?: string;
    icon?: ReactNode;
    onClick?: () => void;
  }) => (
    <button type="button" className={className} onClick={onClick}>
      {icon}
      {children}
    </button>
  ),
}));

describe('EmptyState', () => {
  it('starts a new conversation from the primary action', () => {
    const onNewConversation = vi.fn();

    render(<EmptyState onNewConversation={onNewConversation} />);

    fireEvent.click(screen.getByRole('button', { name: /agent\.emptyState\.newConversation/i }));

    expect(onNewConversation).toHaveBeenCalledTimes(1);
  });

  it('keeps suggestion prompts actionable without using a card grid', () => {
    const onSendPrompt = vi.fn();

    render(<EmptyState onNewConversation={vi.fn()} onSendPrompt={onSendPrompt} />);

    fireEvent.click(
      screen.getByRole('button', { name: /agent\.emptyState\.cards\.analyzeTrends/i })
    );

    expect(onSendPrompt).toHaveBeenCalledTimes(1);
    expect(onSendPrompt).toHaveBeenCalledWith('agent.emptyState.cards.analyzeTrendsPrompt');
  });

  it('resumes the last conversation when available', () => {
    const onResumeConversation = vi.fn();

    render(
      <EmptyState
        onNewConversation={vi.fn()}
        lastConversation={{ id: 'conv-1', title: 'Previous analysis' }}
        onResumeConversation={onResumeConversation}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /previous analysis/i }));

    expect(onResumeConversation).toHaveBeenCalledWith('conv-1');
  });
});
