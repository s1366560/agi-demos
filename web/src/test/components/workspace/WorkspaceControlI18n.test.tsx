import { describe, expect, it, vi } from 'vitest';

import { ObjectiveCreateModal } from '@/components/workspace/objectives/ObjectiveCreateModal';

import { render, screen } from '../../utils';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: string | ({ defaultValue?: string } & Record<string, unknown>)) => {
      const fallback = typeof options === 'string' ? options : (options?.defaultValue ?? _key);
      if (typeof options === 'string') {
        return fallback;
      }
      return fallback.replace(/\{\{(\w+)\}\}/g, (_match, token: string) =>
        String(options?.[token] ?? '')
      );
    },
    i18n: { language: 'en-US', changeLanguage: vi.fn() },
  }),
}));

describe('workspace localized controls', () => {
  it('renders objective modal labels and controls through translation fallbacks', async () => {
    render(
      <ObjectiveCreateModal open onClose={vi.fn()} onSubmit={vi.fn()} parentObjectives={[]} />
    );

    expect(await screen.findByText('Create Objective/Key Result')).toBeInTheDocument();
    expect(screen.getByText('Title')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('E.g., Increase Q3 Revenue')).toBeInTheDocument();
    expect(screen.getByText('Description')).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Add some details about this objective…')
    ).toBeInTheDocument();
    expect(screen.getByText('Type')).toBeInTheDocument();
    expect(screen.getByText('Progress (%)')).toBeInTheDocument();
    expect(screen.getByText('Create')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });
});
