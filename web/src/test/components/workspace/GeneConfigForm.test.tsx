import { describe, expect, it, vi } from 'vitest';

import { GeneConfigForm } from '@/components/workspace/genes/GeneConfigForm';
import type { GeneConfigDraft } from '@/types/geneConfig';

import { render, screen } from '../../utils';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
    i18n: { language: 'en-US', changeLanguage: vi.fn() },
  }),
}));

describe('GeneConfigForm', () => {
  it('renders localized string-list controls', () => {
    const draft: GeneConfigDraft = {
      values: {
        system_prompt: '',
        trigger_keywords: ['audit'],
        model: '',
        temperature: 0.7,
      },
      extra: {},
    };

    render(<GeneConfigForm category="skill" draft={draft} onChange={vi.fn()} />);

    expect(screen.getByText('Add')).toBeInTheDocument();
    expect(screen.getByLabelText('Remove item')).toBeInTheDocument();
  });

  it('renders localized key-value controls', () => {
    const draft: GeneConfigDraft = {
      values: {
        tool_id: '',
        parameters: { timeout: '30' },
      },
      extra: {},
    };

    render(<GeneConfigForm category="tool" draft={draft} onChange={vi.fn()} />);

    expect(screen.getByPlaceholderText('key')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('value')).toBeInTheDocument();
    expect(screen.getByText('Add entry')).toBeInTheDocument();
    expect(screen.getByLabelText('Remove entry')).toBeInTheDocument();
  });
});
