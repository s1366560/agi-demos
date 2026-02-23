/**
 * SearchHeader Component Tests
 *
 * Tests for the SearchHeader composite component.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import type { SearchMode } from '@/hooks/useSearchState';

import { SearchHeader } from '@/components/project/search/SearchHeader';

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const mockProps = {
  searchMode: 'semantic' as SearchMode,
  setSearchMode: vi.fn(),
  query: '',
  startEntityUuid: '',
  communityUuid: '',
  setQuery: vi.fn(),
  setStartEntityUuid: vi.fn(),
  setCommunityUuid: vi.fn(),
  onSearch: vi.fn(),
  loading: false,
  isSearchFocused: false,
  isConfigOpen: true,
  isListening: false,
  showHistory: false,
  setIsSearchFocused: vi.fn(),
  toggleConfigOpen: vi.fn(),
  setShowHistory: vi.fn(),
  setShowMobileConfig: vi.fn(),
  onVoiceSearch: vi.fn(),
  searchHistory: [],
  hasResults: false,
  onExportResults: vi.fn(),
  isMobile: false,
};

describe('SearchHeader', () => {
  describe('Rendering', () => {
    it('should render all search mode buttons', () => {
      render(<SearchHeader {...mockProps} />);

      expect(screen.getByText('project.search.modes.semantic')).toBeInTheDocument();
      expect(screen.getByText('project.search.modes.graph')).toBeInTheDocument();
      expect(screen.getByText('project.search.modes.temporal')).toBeInTheDocument();
      expect(screen.getByText('project.search.modes.faceted')).toBeInTheDocument();
      expect(screen.getByText('project.search.modes.community')).toBeInTheDocument();
    });

    it('should highlight active search mode', () => {
      render(<SearchHeader {...mockProps} searchMode="graphTraversal" />);

      const graphButton = screen.getByText('project.search.modes.graph').closest('button');
      expect(graphButton).toHaveClass('bg-blue-600');
    });

    it('should render search input', () => {
      render(<SearchHeader {...mockProps} />);

      const input = screen.getByPlaceholderText('project.search.input.placeholder.default');
      expect(input).toBeInTheDocument();
    });

    it('should render search button', () => {
      render(<SearchHeader {...mockProps} />);

      expect(screen.getByText('project.search.actions.retrieve')).toBeInTheDocument();
    });

    it('should render config toggle on desktop', () => {
      render(<SearchHeader {...mockProps} />);

      // Config button should be present
      const buttons = screen.getAllByRole('button');
      const configButton = buttons.find((btn) => btn.querySelector('svg'));
      expect(configButton).toBeInTheDocument();
    });
  });

  describe('Search Mode Changes', () => {
    it('should call setSearchMode when semantic mode is clicked', () => {
      const { setSearchMode } = mockProps;
      render(<SearchHeader {...mockProps} searchMode="graphTraversal" />);

      const semanticButton = screen.getByText('project.search.modes.semantic').closest('button');
      fireEvent.click(semanticButton!);

      expect(setSearchMode).toHaveBeenCalledWith('semantic');
    });

    it('should call setSearchMode when graph mode is clicked', () => {
      const { setSearchMode } = mockProps;
      render(<SearchHeader {...mockProps} />);

      const graphButton = screen.getByText('project.search.modes.graph').closest('button');
      fireEvent.click(graphButton!);

      expect(setSearchMode).toHaveBeenCalledWith('graphTraversal');
    });
  });

  describe('Input Handling', () => {
    it('should update query in semantic mode', () => {
      const { setQuery } = mockProps;
      render(<SearchHeader {...mockProps} searchMode="semantic" />);

      const input = screen.getByPlaceholderText('project.search.input.placeholder.default');
      fireEvent.change(input, { target: { value: 'test query' } });

      expect(setQuery).toHaveBeenCalledWith('test query');
    });

    it('should update startEntityUuid in graphTraversal mode', () => {
      const { setStartEntityUuid } = mockProps;
      render(<SearchHeader {...mockProps} searchMode="graphTraversal" />);

      const input = screen.getByPlaceholderText('project.search.input.placeholder.graph');
      fireEvent.change(input, { target: { value: 'uuid-123' } });

      expect(setStartEntityUuid).toHaveBeenCalledWith('uuid-123');
    });

    it('should update communityUuid in community mode', () => {
      const { setCommunityUuid } = mockProps;
      render(<SearchHeader {...mockProps} searchMode="community" />);

      const input = screen.getByPlaceholderText('project.search.input.placeholder.community');
      fireEvent.change(input, { target: { value: 'community-123' } });

      expect(setCommunityUuid).toHaveBeenCalledWith('community-123');
    });

    it('should call onSearch when Enter key is pressed', () => {
      const { onSearch } = mockProps;
      render(<SearchHeader {...mockProps} />);

      const input = screen.getByPlaceholderText('project.search.input.placeholder.default');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(onSearch).toHaveBeenCalled();
    });
  });

  describe('Search Button', () => {
    it('should call onSearch when clicked', () => {
      const { onSearch } = mockProps;
      render(<SearchHeader {...mockProps} />);

      const searchButton = screen.getByText('project.search.actions.retrieve').closest('button');
      fireEvent.click(searchButton!);

      expect(onSearch).toHaveBeenCalled();
    });

    it('should show loading state when loading is true', () => {
      render(<SearchHeader {...mockProps} loading={true} />);

      expect(screen.getByText('project.search.actions.searching')).toBeInTheDocument();
    });

    it('should disable button when loading', () => {
      render(<SearchHeader {...mockProps} loading={true} />);

      const searchButton = screen.getByText('project.search.actions.searching').closest('button');
      expect(searchButton).toBeDisabled();
    });
  });

  describe('Config Toggle', () => {
    it('should call toggleConfigOpen when clicked', () => {
      const { toggleConfigOpen } = mockProps;
      render(<SearchHeader {...mockProps} />);

      const buttons = screen.getAllByRole('button');
      // Find the config toggle button (last button in the header)
      const configButton = buttons.find((btn) => {
        const svg = btn.querySelector('svg');
        return svg && btn.getAttribute('title')?.includes('Config');
      });

      if (configButton) {
        fireEvent.click(configButton);
        expect(toggleConfigOpen).toHaveBeenCalled();
      }
    });
  });

  describe('History Button', () => {
    it('should show history button when there is history', () => {
      render(
        <SearchHeader
          {...mockProps}
          searchHistory={[{ query: 'test', mode: 'semantic', timestamp: Date.now() }]}
        />
      );

      // The button should contain the history icon (MessageSquare)
      const buttons = screen.getAllByRole('button');
      const historyButton = buttons.find((btn) => btn.textContent?.includes('1'));
      expect(historyButton).toBeInTheDocument();
    });

    it('should not show history button when history is empty', () => {
      render(<SearchHeader {...mockProps} searchHistory={[]} />);

      // Check that no button contains the count (1)
      const buttons = screen.getAllByRole('button');
      const historyButton = buttons.find((btn) => btn.textContent?.includes('1'));
      expect(historyButton).toBeUndefined();
    });

    it('should call setShowHistory when history button is clicked', () => {
      const { setShowHistory } = mockProps;
      render(
        <SearchHeader
          {...mockProps}
          searchHistory={[{ query: 'test', mode: 'semantic', timestamp: Date.now() }]}
        />
      );

      const buttons = screen.getAllByRole('button');
      const historyButton = buttons.find((btn) => btn.textContent?.includes('1'));
      if (historyButton) fireEvent.click(historyButton);

      expect(setShowHistory).toHaveBeenCalled();
    });
  });

  describe('Export Button', () => {
    it('should show export button when there are results', () => {
      render(<SearchHeader {...mockProps} hasResults={true} />);

      expect(screen.getByText('project.search.actions.export')).toBeInTheDocument();
    });

    it('should not show export button when there are no results', () => {
      render(<SearchHeader {...mockProps} hasResults={false} />);

      expect(screen.queryByText('project.search.actions.export')).not.toBeInTheDocument();
    });

    it('should call onExportResults when clicked', () => {
      const { onExportResults } = mockProps;
      render(<SearchHeader {...mockProps} hasResults={true} />);

      const exportButton = screen.getByText('project.search.actions.export').closest('button');
      fireEvent.click(exportButton!);

      expect(onExportResults).toHaveBeenCalled();
    });
  });

  describe('Voice Search', () => {
    it('should show voice button in semantic mode', () => {
      render(<SearchHeader {...mockProps} searchMode="semantic" />);

      const voiceButton = screen.getByTitle('project.search.input.voice_search');
      expect(voiceButton).toBeInTheDocument();
    });

    it('should show voice button in temporal mode', () => {
      render(<SearchHeader {...mockProps} searchMode="temporal" />);

      const voiceButton = screen.getByTitle('project.search.input.voice_search');
      expect(voiceButton).toBeInTheDocument();
    });

    it('should show voice button in faceted mode', () => {
      render(<SearchHeader {...mockProps} searchMode="faceted" />);

      const voiceButton = screen.getByTitle('project.search.input.voice_search');
      expect(voiceButton).toBeInTheDocument();
    });

    it('should not show voice button in graphTraversal mode', () => {
      render(<SearchHeader {...mockProps} searchMode="graphTraversal" />);

      const voiceButton = screen.queryByTitle('project.search.input.voice_search');
      expect(voiceButton).not.toBeInTheDocument();
    });

    it('should call onVoiceSearch when voice button is clicked', () => {
      const { onVoiceSearch } = mockProps;
      render(<SearchHeader {...mockProps} searchMode="semantic" />);

      const voiceButton = screen.getByTitle('project.search.input.voice_search');
      fireEvent.click(voiceButton);

      expect(onVoiceSearch).toHaveBeenCalled();
    });

    it('should show listening state when isListening is true', () => {
      render(<SearchHeader {...mockProps} searchMode="semantic" isListening={true} />);

      const voiceButton = screen.getByTitle('project.search.input.listening');
      expect(voiceButton).toBeInTheDocument();
    });
  });

  describe('Search History Dropdown', () => {
    it('should render history dropdown when showHistory is true', () => {
      render(
        <SearchHeader
          {...mockProps}
          showHistory={true}
          searchHistory={[
            { query: 'test1', mode: 'semantic', timestamp: Date.now() },
            { query: 'test2', mode: 'graphTraversal', timestamp: Date.now() },
          ]}
        />
      );

      expect(screen.getByText('project.search.actions.recent')).toBeInTheDocument();
      expect(screen.getByText('test1')).toBeInTheDocument();
      expect(screen.getByText('test2')).toBeInTheDocument();
    });

    it('should call setQuery and setSearchMode when history item is clicked', () => {
      const { setQuery, setSearchMode } = mockProps;
      render(
        <SearchHeader
          {...mockProps}
          showHistory={true}
          searchHistory={[{ query: 'test query', mode: 'graphTraversal', timestamp: Date.now() }]}
        />
      );

      const historyItem = screen.getByText('test query').closest('button');
      fireEvent.click(historyItem!);

      expect(setQuery).toHaveBeenCalledWith('test query');
      expect(setSearchMode).toHaveBeenCalledWith('graphTraversal');
    });
  });

  describe('Mobile Config Button', () => {
    it('should show mobile config button when isMobile is true', () => {
      render(<SearchHeader {...mockProps} isMobile={true} />);

      const buttons = screen.getAllByRole('button');
      const hasSlidersIcon = buttons.some((btn) => btn.querySelector('svg'));
      expect(hasSlidersIcon).toBe(true);
    });
  });

  describe('Input Focus State', () => {
    it('should call setIsSearchFocused on focus', () => {
      const { setIsSearchFocused } = mockProps;
      render(<SearchHeader {...mockProps} />);

      const input = screen.getByPlaceholderText('project.search.input.placeholder.default');
      fireEvent.focus(input);

      expect(setIsSearchFocused).toHaveBeenCalledWith(true);
    });

    it('should call setIsSearchFocused on blur', () => {
      const { setIsSearchFocused } = mockProps;
      render(<SearchHeader {...mockProps} />);

      const input = screen.getByPlaceholderText('project.search.input.placeholder.default');
      fireEvent.blur(input);

      expect(setIsSearchFocused).toHaveBeenCalledWith(false);
    });
  });
});
