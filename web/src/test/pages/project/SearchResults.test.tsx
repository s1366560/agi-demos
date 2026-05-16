import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SearchResults } from '@/pages/project/search';

describe('SearchResults', () => {
  it('uses responsive non-overflowing header layout', () => {
    render(
      <SearchResults
        results={[]}
        loading={false}
        isResultsCollapsed={false}
        viewMode="grid"
        copiedId={null}
        selectedSubgraphIds={[]}
        onResultsCollapseToggle={vi.fn()}
        onViewModeChange={vi.fn()}
        onResultClick={vi.fn()}
        onCopyId={vi.fn()}
      />
    );

    const heading = screen.getByRole('heading', { name: 'Retrieval Results' });
    expect(heading.closest('section')).toHaveClass('min-w-0');
    expect(heading.closest('.cursor-pointer')).toHaveClass('flex-col');
  });
});
