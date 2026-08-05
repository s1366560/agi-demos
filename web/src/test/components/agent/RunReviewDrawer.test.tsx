import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RunReviewDrawer } from '@/components/agent/review/RunReviewDrawer';

describe('RunReviewDrawer', () => {
  it('keeps an accessible trigger name when the responsive label is hidden', () => {
    render(
      <RunReviewDrawer
        run={{
          conversation_id: 'conversation-1',
          run_id: 'run-1',
          turn_id: 'turn-1',
          run_revision: 1,
          status: 'completed',
          allowed_actions: [],
          authority_revision: 1,
        }}
      />
    );

    expect(screen.getByRole('button', { name: 'Run review' })).toHaveAttribute(
      'aria-label',
      'Run review'
    );
  });
});
