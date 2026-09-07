import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SearchResults } from '@/pages/project/search';

describe('SearchResults', () => {
  it.each(['grid', 'list'] as const)(
    'does not invent a relevance score for traversal in %s mode',
    (viewMode) => {
      render(
        <SearchResults
          results={[
            {
              content: 'Graph node',
              score: null,
              source: 'Graph traversal',
              metadata: { type: 'Entity', uuid: 'node-1' },
            },
          ]}
          loading={false}
          isResultsCollapsed={false}
          viewMode={viewMode}
          copiedId={null}
          selectedSubgraphIds={[]}
          onResultsCollapseToggle={vi.fn()}
          onViewModeChange={vi.fn()}
          onResultClick={vi.fn()}
          onCopyId={vi.fn()}
        />
      );
      expect(screen.queryByText('0%')).not.toBeInTheDocument();
      expect(screen.queryByText('unknown')).not.toBeInTheDocument();
    }
  );
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
    expect(heading.closest('button')).toHaveClass('min-w-0', 'flex-wrap');
    expect(heading.closest('button')?.parentElement).toHaveClass('flex-col');
  });
});
