import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SearchForm } from '../../../../pages/project/search/components/SearchForm';

const baseProps = {
  searchMode: 'semantic' as const,
  query: 'memory query',
  startEntityUuid: '',
  communityUuid: '',
  isSearchFocused: false,
  isListening: false,
  loading: false,
  isConfigOpen: false,
  searchHistory: [],
  showHistory: false,
  onSearchModeChange: vi.fn(),
  onQueryChange: vi.fn(),
  onStartEntityUuidChange: vi.fn(),
  onCommunityUuidChange: vi.fn(),
  onSearchFocusChange: vi.fn(),
  onSearch: vi.fn(),
  onVoiceSearch: vi.fn(),
  onConfigToggle: vi.fn(),
  onHistoryToggle: vi.fn(),
  onHistoryItemClick: vi.fn(),
};

describe('SearchForm', () => {
  it('names the query input for assistive technologies', () => {
    render(<SearchForm {...baseProps} />);

    expect(screen.getByRole('searchbox', { name: 'Search query' })).toHaveValue('memory query');
  });

  it('renders a working export action when results can be exported', () => {
    const onExportResults = vi.fn();

    render(<SearchForm {...baseProps} onExportResults={onExportResults} canExportResults={true} />);

    const exportButton = screen.getByRole('button', { name: 'Export' });
    expect(exportButton).toBeEnabled();

    fireEvent.click(exportButton);

    expect(onExportResults).toHaveBeenCalledTimes(1);
  });

  it('keeps the export action disabled until a search has results', () => {
    const onExportResults = vi.fn();

    render(
      <SearchForm {...baseProps} onExportResults={onExportResults} canExportResults={false} />
    );

    const exportButton = screen.getByRole('button', { name: 'Export' });
    expect(exportButton).toBeDisabled();

    fireEvent.click(exportButton);

    expect(onExportResults).not.toHaveBeenCalled();
  });
});
