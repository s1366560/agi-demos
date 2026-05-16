import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SearchConfig } from '@/pages/project/search';

const baseProps = {
  searchMode: 'semantic' as const,
  configTab: 'params' as const,
  isConfigOpen: true,
  showMobileConfig: true,
  retrievalMode: 'hybrid' as const,
  strategy: 'balanced',
  focalNode: '',
  crossEncoder: '',
  maxDepth: 2,
  relationshipTypes: [],
  timeRange: 'all',
  customTimeRange: {},
  selectedEntityTypes: [],
  selectedTags: [],
  availableTags: [],
  communityUuid: '',
  includeEpisodes: true,
  onMobileConfigClose: vi.fn(),
  onConfigTabChange: vi.fn(),
  onRetrievalModeChange: vi.fn(),
  onStrategyChange: vi.fn(),
  onFocalNodeChange: vi.fn(),
  onCrossEncoderChange: vi.fn(),
  onMaxDepthChange: vi.fn(),
  onRelationshipTypesChange: vi.fn(),
  onTimeRangeChange: vi.fn(),
  onCustomTimeRangeChange: vi.fn(),
  onSelectedEntityTypesChange: vi.fn(),
  onSelectedTagsChange: vi.fn(),
  onIncludeEpisodesChange: vi.fn(),
  showTooltip: null,
  onShowTooltip: vi.fn(),
};

describe('SearchConfig', () => {
  it('labels the mobile close button', () => {
    const onMobileConfigClose = vi.fn();

    render(<SearchConfig {...baseProps} onMobileConfigClose={onMobileConfigClose} />);

    const closeButton = screen.getByRole('button', { name: 'Close' });
    fireEvent.click(closeButton);

    expect(onMobileConfigClose).toHaveBeenCalledTimes(1);
  });

  it('adds a custom faceted tag through the add tag control', () => {
    const onSelectedTagsChange = vi.fn();

    render(
      <SearchConfig
        {...baseProps}
        searchMode="faceted"
        configTab="filters"
        onSelectedTagsChange={onSelectedTagsChange}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    fireEvent.change(screen.getByLabelText('New tag'), {
      target: { value: 'roadmap' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add tag' }));

    expect(onSelectedTagsChange).toHaveBeenCalledWith(['roadmap']);
  });
});
