import { useParams } from 'react-router-dom';

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { Maintenance } from '../../../pages/project/Maintenance';
import { graphService } from '../../../services/graphService';

vi.mock('../../../services/graphService', () => ({
  graphService: {
    getGraphStats: vi.fn().mockResolvedValue({
      entity_count: 100,
      episodic_count: 50,
      community_count: 5,
      edge_count: 200,
    }),
    getEmbeddingStatus: vi.fn().mockResolvedValue({
      total_entities: 100,
      embedded_entities: 95,
      pending_entities: 5,
    }),
    exportData: vi.fn().mockResolvedValue({ some: 'data' }),
    incrementalRefresh: vi.fn().mockResolvedValue({ episodes_processed: 10 }),
    deduplicateEntities: vi.fn().mockResolvedValue({ duplicates_found: 5 }),
    invalidateStaleEdges: vi.fn(),
    getMaintenanceStatus: vi.fn().mockResolvedValue({
      recommendations: [],
    }),
    rebuildCommunities: vi.fn().mockResolvedValue({ status: 'submitted' }),
  },
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useParams: vi.fn().mockReturnValue({ projectId: 'p1' }),
  };
});

// Mock fetch for direct API calls in Maintenance component
globalThis.fetch = vi.fn();

describe('Maintenance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useParams as any).mockReturnValue({ projectId: 'p1' });
  });

  it('renders graph statistics', async () => {
    render(<Maintenance />);

    await waitFor(() => {
      expect(screen.getByText('100')).toBeInTheDocument(); // Entities
      expect(screen.getByText('50')).toBeInTheDocument(); // Episodes
      expect(screen.getByText('5')).toBeInTheDocument(); // Communities
    });
  });

  it('handles incremental refresh', async () => {
    (graphService.incrementalRefresh as any).mockResolvedValue({ episodes_to_process: 10 });

    render(<Maintenance />);

    const refreshBtn = screen.getAllByText('Refresh')[0]; // There might be multiple "Refresh" texts
    fireEvent.click(refreshBtn);

    expect(screen.getByText('Refreshing...')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Successfully refreshed 10 episodes')).toBeInTheDocument();
    });
  });

  it('handles deduplication check', async () => {
    (graphService.deduplicateEntities as any).mockResolvedValue({ duplicates_found: 5 });

    render(<Maintenance />);

    const checkBtn = screen.getByText('Check for Duplicates');
    fireEvent.click(checkBtn);

    await waitFor(() => {
      expect(screen.getByText('Found 5 duplicate entities')).toBeInTheDocument();
    });
  });

  it('handles community rebuild', async () => {
    (graphService.rebuildCommunities as any).mockResolvedValue({
      status: 'submitted',
      task_id: 'task-123',
    });

    render(<Maintenance />);

    const rebuildBtn = screen.getByText('Rebuild');
    fireEvent.click(rebuildBtn);

    expect(screen.getByText('Rebuilding...')).toBeInTheDocument();

    await waitFor(() => {
      expect(graphService.rebuildCommunities).toHaveBeenCalledWith(true, 'p1');
      expect(screen.getByText('Community rebuild started (Task ID: task-123)')).toBeInTheDocument();
    });
  });

  it('handles data export', async () => {
    (graphService.exportData as any).mockResolvedValue({ some: 'data' });

    // Mock URL.createObjectURL
    globalThis.URL.createObjectURL = vi.fn();
    globalThis.URL.revokeObjectURL = vi.fn();

    render(<Maintenance />);

    fireEvent.click(screen.getByText('Export'));

    await waitFor(() => {
      expect(graphService.exportData).toHaveBeenCalled();
      expect(screen.getByText('Data exported successfully')).toBeInTheDocument();
    });
  });
});
