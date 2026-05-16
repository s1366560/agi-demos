import { describe, expect, it, vi } from 'vitest';

import { SearchResults } from '../../../../pages/project/search/components/SearchResults';
import { render, screen } from '../../../utils';

const baseProps = {
  loading: false,
  isResultsCollapsed: false,
  viewMode: 'grid' as const,
  copiedId: null,
  selectedSubgraphIds: [],
  onResultsCollapseToggle: vi.fn(),
  onViewModeChange: vi.fn(),
  onResultClick: vi.fn(),
  onCopyId: vi.fn(),
};

describe('SearchResults', () => {
  it('renders a real empty state instead of a fake result card', () => {
    render(<SearchResults {...baseProps} results={[]} />);

    expect(screen.getByText('No retrieval results')).toBeInTheDocument();
    expect(
      screen.getByText('Adjust the query, search mode, or filters and run retrieval again.')
    ).toBeInTheDocument();
    expect(screen.queryByText('Architecture Specs v2.pdf')).not.toBeInTheDocument();
    expect(screen.queryByText('98%')).not.toBeInTheDocument();
  });

  it('does not show the empty state while results are loading', () => {
    render(<SearchResults {...baseProps} results={[]} loading />);

    expect(screen.queryByText('No retrieval results')).not.toBeInTheDocument();
  });
});
