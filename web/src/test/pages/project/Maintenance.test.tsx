import { useParams } from 'react-router-dom';

import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
      current_provider: 'openai',
      current_dimension: 1536,
      is_compatible: true,
      missing_embeddings: 5,
    }),
    exportData: vi.fn().mockResolvedValue({ some: 'data' }),
    incrementalRefresh: vi.fn().mockResolvedValue({ episodes_processed: 10 }),
    deduplicateEntities: vi.fn().mockResolvedValue({ duplicates_found: 5 }),
    invalidateStaleEdges: vi.fn().mockResolvedValue({ stale_edges_found: 0, deleted: 0 }),
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

function deferred<T>() {
  let resolve: (value: T | PromiseLike<T>) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

describe('Maintenance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useParams as any).mockReturnValue({ projectId: 'p1' });
    (graphService.getMaintenanceStatus as any).mockResolvedValue({ recommendations: [] });
    (graphService.invalidateStaleEdges as any).mockResolvedValue({
      stale_edges_found: 0,
      deleted: 0,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders graph statistics', async () => {
    render(<Maintenance />);

    await waitFor(() => {
      expect(graphService.getGraphStats).toHaveBeenCalledWith(undefined, 'p1');
      expect(graphService.getMaintenanceStatus).toHaveBeenCalledWith('p1');
      expect(screen.getByText('100')).toBeInTheDocument(); // Entities
      expect(screen.getByText('50')).toBeInTheDocument(); // Episodes
      expect(screen.getByText('5')).toBeInTheDocument(); // Communities
    });
  });

  it('shows a visible error when initial maintenance data fails to load', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    (graphService.getGraphStats as any).mockRejectedValueOnce(new Error('stats down'));

    render(<Maintenance />);

    expect(await screen.findByText('Failed to load maintenance data')).toBeInTheDocument();
  });

  it('handles incremental refresh', async () => {
    (graphService.incrementalRefresh as any).mockResolvedValue({ episodes_to_process: 10 });

    render(<Maintenance />);

    const refreshBtn = screen.getAllByText('Refresh')[0]; // There might be multiple "Refresh" texts
    fireEvent.click(refreshBtn);

    expect(screen.getByText('Refreshing...')).toBeInTheDocument();

    await waitFor(() => {
      expect(graphService.incrementalRefresh).toHaveBeenCalledWith({ project_id: 'p1' });
      expect(screen.getByText('Successfully refreshed 10 episodes')).toBeInTheDocument();
    });
  });

  it('handles deduplication check', async () => {
    (graphService.deduplicateEntities as any).mockResolvedValue({ duplicates_found: 5 });

    render(<Maintenance />);

    const checkBtn = screen.getByText('Check for Duplicates');
    fireEvent.click(checkBtn);

    await waitFor(() => {
      expect(graphService.deduplicateEntities).toHaveBeenCalledWith({
        dry_run: true,
        project_id: 'p1',
      });
      expect(screen.getByText('Found 5 duplicate entities')).toBeInTheDocument();
    });
  });

  it('starts deduplication merge through the maintenance API', async () => {
    (graphService.deduplicateEntities as any).mockResolvedValue({
      dry_run: false,
      task_id: 'dedup-task-1',
    });

    render(<Maintenance />);

    fireEvent.click(screen.getByText('Merge Duplicates'));

    expect(screen.getByText('Deduplicating...')).toBeInTheDocument();

    await waitFor(() => {
      expect(graphService.deduplicateEntities).toHaveBeenCalledWith({
        dry_run: false,
        project_id: 'p1',
      });
      expect(screen.getByText('Deduplication started (Task ID: dedup-task-1)')).toBeInTheDocument();
    });
  });

  it('ignores stale maintenance status refreshes after project changes', async () => {
    const staleStatus = deferred<{
      recommendations: Array<{ type: string; priority: string; message: string }>;
    }>();
    (graphService.getMaintenanceStatus as any)
      .mockResolvedValueOnce({ recommendations: [] })
      .mockReturnValueOnce(staleStatus.promise)
      .mockResolvedValueOnce({
        recommendations: [
          {
            type: 'project_two',
            priority: 'high',
            message: 'Project two recommendation',
          },
        ],
      });
    (graphService.deduplicateEntities as any).mockResolvedValueOnce({
      dry_run: false,
      task_id: 'dedup-task-1',
    });

    const view = render(<Maintenance />);

    await waitFor(() => {
      expect(graphService.getMaintenanceStatus).toHaveBeenCalledWith('p1');
    });

    fireEvent.click(screen.getByText('Merge Duplicates'));

    await waitFor(() => {
      expect(graphService.deduplicateEntities).toHaveBeenCalledWith({
        dry_run: false,
        project_id: 'p1',
      });
      expect(graphService.getMaintenanceStatus).toHaveBeenCalledTimes(2);
    });

    (useParams as any).mockReturnValue({ projectId: 'p2' });
    view.rerender(<Maintenance />);

    expect(await screen.findByText('Project two recommendation')).toBeInTheDocument();

    await act(async () => {
      staleStatus.resolve({
        recommendations: [
          {
            type: 'stale_project_one',
            priority: 'high',
            message: 'Stale project one recommendation',
          },
        ],
      });
      await staleStatus.promise;
    });

    expect(screen.getByText('Project two recommendation')).toBeInTheDocument();
    expect(screen.queryByText('Stale project one recommendation')).not.toBeInTheDocument();
  });

  it('checks stale edges through the maintenance API', async () => {
    (graphService.invalidateStaleEdges as any).mockResolvedValue({ stale_edges_found: 7 });

    render(<Maintenance />);

    fireEvent.click(screen.getByText('Check Stale Edges'));

    await waitFor(() => {
      expect(graphService.invalidateStaleEdges).toHaveBeenCalledWith({
        dry_run: true,
        project_id: 'p1',
      });
      expect(screen.getByText('Found 7 stale edges')).toBeInTheDocument();
    });
  });

  it('cleans stale edges through the maintenance API', async () => {
    (graphService.invalidateStaleEdges as any).mockResolvedValue({ deleted: 3 });

    render(<Maintenance />);

    fireEvent.click(screen.getByText('Clean'));

    expect(screen.getByText('Cleaning...')).toBeInTheDocument();

    await waitFor(() => {
      expect(graphService.invalidateStaleEdges).toHaveBeenCalledWith({
        dry_run: false,
        project_id: 'p1',
      });
      expect(screen.getByText('Deleted 3 stale edges')).toBeInTheDocument();
    });
  });

  it('renders maintenance recommendations from the backend', async () => {
    (graphService.getMaintenanceStatus as any).mockResolvedValue({
      recommendations: [
        {
          type: 'cleanup',
          priority: 'medium',
          message: 'Consider cleaning up 1200 episodes older than 90 days',
        },
      ],
    });

    render(<Maintenance />);

    expect(
      await screen.findByText('Consider cleaning up 1200 episodes older than 90 days')
    ).toBeInTheDocument();
    expect(screen.queryByText(/Found 45 potential/)).not.toBeInTheDocument();
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
      expect(graphService.exportData).toHaveBeenCalledWith({
        tenant_id: undefined,
        project_id: 'p1',
      });
      expect(screen.getByText('Data exported successfully')).toBeInTheDocument();
    });
  });
});
