import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, defaultValue?: string) =>
        typeof defaultValue === 'string' ? defaultValue : key,
      i18n: { language: 'en' },
    }),
  };
});

import { InlineEvent } from '@business/agent/ui/web/transcript/messageBubble/inlineEvents';

describe('inline transcript events', () => {
  it('shows an error as an alert where it happened', () => {
    render(
      <InlineEvent
        event={{ id: 'e1', type: 'error', message: 'Initialization failed', timestamp: 1 }}
      />
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Initialization failed');
    expect(screen.getByRole('alert')).toHaveTextContent('agent.chat.errors.title');
  });

  it('shows a decision with the answer that was given', () => {
    render(
      <InlineEvent
        event={{
          id: 'd1',
          type: 'decision_asked',
          requestId: 'r1',
          question: 'Which report?',
          decisionType: 'single_choice',
          options: [
            { id: 'a', label: 'Summary' },
            { id: 'b', label: 'Full report' },
          ],
          allowCustom: false,
          answered: true,
          decision: 'Full report',
          timestamp: 1,
        }}
      />
    );
    expect(screen.getByText('Needs decision')).toBeInTheDocument();
    expect(screen.getByText('Which report?')).toBeInTheDocument();
    expect(screen.getByText('Full report')).toBeInTheDocument();
    expect(screen.getByText('Summary')).toBeInTheDocument();
  });

  it('shows an environment-variable request with the variables it asked for', () => {
    render(
      <InlineEvent
        event={{
          id: 'v1',
          type: 'env_var_requested',
          requestId: 'r1',
          toolName: 'bash',
          fields: [
            {
              name: 'RETEST_VAR',
              label: 'Retest variable',
              description: 'Checks the request path',
              required: false,
              input_type: 'password',
            },
          ],
          answered: true,
          providedVariables: ['RETEST_VAR'],
          timestamp: 1,
        }}
      />
    );
    expect(screen.getByText('Needs configuration')).toBeInTheDocument();
    expect(screen.getByText('Retest variable')).toBeInTheDocument();
    // An answered request does not ask again.
    expect(screen.queryByRole('button', { name: 'Submit' })).not.toBeInTheDocument();
  });

  it('shows an answer recorded on its own as an answered card', () => {
    render(
      <InlineEvent
        event={{
          id: 'r1',
          type: 'permission_replied',
          requestId: 'p1',
          granted: true,
          timestamp: 1,
        }}
      />
    );
    expect(screen.getByText('Needs permission')).toBeInTheDocument();
    expect(screen.getByText('Decision recorded')).toBeInTheDocument();
  });

  it('shows a permission with the verdict that was recorded on its own event', () => {
    render(
      <InlineEvent
        event={{
          id: 'r1',
          type: 'permission_replied',
          requestId: 'p1',
          granted: false,
          toolName: 'bash',
          description: 'Run bash',
          timestamp: 1,
        }}
      />
    );
    // A verdict without its request names no tool to decide about.
    expect(screen.getByText('Decision recorded')).toBeInTheDocument();
    expect(screen.queryByText('Run bash')).not.toBeInTheDocument();
  });

  it('draws nothing for an event the transcript does not show', () => {
    const { container } = render(
      <InlineEvent event={{ id: 'k1', type: 'task_updated', timestamp: 1 }} />
    );
    expect(container).toBeEmptyDOMElement();
  });
});
