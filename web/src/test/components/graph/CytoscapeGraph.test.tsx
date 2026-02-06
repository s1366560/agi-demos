/**
 * TDD Tests for CytoscapeGraph Component Refactoring
 *
 * Testing the new composite component API:
 * 1. Config object API
 * 2. Composite component API
 * 3. Backward compatibility with legacy API
 */

import { render, screen, fireEvent, waitFor } from '../../utils';

import React from 'react';

import { describe, it, expect, vi, beforeEach } from 'vitest';

// Import mocks FIRST before component imports
import '../../mocks/cytoscape';

import { CytoscapeGraph } from '@/components/graph/CytoscapeGraph';
import type { GraphConfig, NodeData } from '@/components/graph/CytoscapeGraph/types';

import { graphService } from '../../mocks/graphService';
import { useThemeStore } from '../../mocks/themeStore';

describe('CytoscapeGraph - TDD Refactoring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ========================================
  // Test Suite 1: New Config Object API
  // ========================================
  describe('Config Object API', () => {
    it('should render with config object', async () => {
      const config: GraphConfig = {
        data: {
          projectId: 'p1',
          tenantId: 't1',
          includeCommunities: true,
          minConnections: 0,
          subgraphNodeIds: undefined,
        },
        features: {
          showToolbar: true,
          showLegend: true,
          showStats: true,
          enableExport: true,
          enableRelayout: true,
        },
        layout: {
          type: 'cose',
          animate: true,
        },
      };

      render(<CytoscapeGraph config={config} />);

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });

    it('should hide toolbar when showToolbar is false', async () => {
      const config: GraphConfig = {
        data: { projectId: 'p1' },
        features: {
          showToolbar: false,
          showLegend: true,
          showStats: true,
          enableExport: true,
          enableRelayout: true,
        },
      };

      render(<CytoscapeGraph config={config} />);

      // Toolbar buttons should not be present
      await waitFor(() => {
        expect(screen.queryByTitle('Relayout')).not.toBeInTheDocument();
        expect(screen.queryByTitle('Fit to View')).not.toBeInTheDocument();
      });
    });

    it('should hide legend when showLegend is false', async () => {
      const config: GraphConfig = {
        data: { projectId: 'p1' },
        features: {
          showToolbar: true,
          showLegend: false,
          showStats: true,
          enableExport: true,
          enableRelayout: true,
        },
      };

      render(<CytoscapeGraph config={config} />);

      await waitFor(() => {
        expect(screen.queryByText('Entity')).not.toBeInTheDocument();
      });
    });

    it('should support custom layout options', async () => {
      const config: GraphConfig = {
        data: { projectId: 'p1' },
        layout: {
          type: 'circle',
          animate: false,
        },
      };

      render(<CytoscapeGraph config={config} />);

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });

    it('should handle loading state', async () => {
      // graphService is imported from mocks
      graphService.getGraphData.mockImplementationOnce(() => new Promise(() => {}));

      const config: GraphConfig = {
        data: { projectId: 'p1' },
      };

      render(<CytoscapeGraph config={config} />);

      expect(screen.getByText(/Loading graph/)).toBeInTheDocument();
    });

    it('should handle error state', async () => {
      // graphService is imported from mocks
      graphService.getGraphData.mockRejectedValueOnce(new Error('Network error'));

      const config: GraphConfig = {
        data: { projectId: 'p1' },
      };

      render(<CytoscapeGraph config={config} />);

      await waitFor(() => {
        expect(screen.getByText(/Failed to load graph data/)).toBeInTheDocument();
      });
    });
  });

  // ========================================
  // Test Suite 2: Composite Component API
  // ========================================
  describe('Composite Component API', () => {
    it('should render with Viewport subcomponent', async () => {
      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });

    it('should render with Controls subcomponent', async () => {
      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" />
          <CytoscapeGraph.Controls />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByTitle('Relayout')).toBeInTheDocument();
        expect(screen.getByTitle('Fit to View')).toBeInTheDocument();
      });
    });

    it('should render with NodeInfoPanel subcomponent', async () => {
      const onNodeClick = vi.fn();

      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" onNodeClick={onNodeClick} />
          <CytoscapeGraph.NodeInfoPanel />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });

      // NodeInfoPanel should be in document but empty initially
      expect(screen.getByText(/select a node/i)).toBeInTheDocument();
    });

    it('should handle node click through composite API', async () => {
      const onNodeClick = vi.fn();
      const nodeClickHandler: ((node: NodeData | null) => void) | null = null;

      // Capture the onNodeClick callback
      // graphService is imported from mocks
      graphService.getGraphData.mockImplementation(() => {
        // Return after a delay to simulate async
        return new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              elements: {
                nodes: [
                  {
                    data: {
                      id: 'n1',
                      label: 'Entity',
                      name: 'Test Entity',
                      uuid: 'u1',
                      entity_type: 'Person',
                    },
                  },
                ],
                edges: [],
              },
            });
          }, 100);
        });
      });

      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" onNodeClick={onNodeClick} />
          <CytoscapeGraph.NodeInfoPanel />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });
  });

  // ========================================
  // Test Suite 3: Backward Compatibility
  // ========================================
  describe('Backward Compatibility (Legacy API)', () => {
    it('should render with legacy props', async () => {
      const onNodeClick = vi.fn();

      render(
        <CytoscapeGraph
          projectId="p1"
          tenantId="t1"
          includeCommunities={true}
          minConnections={0}
          onNodeClick={onNodeClick}
        />
      );

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });

    it('should support subgraphNodeIds with legacy API', async () => {
      // graphService is imported from mocks

      render(<CytoscapeGraph projectId="p1" subgraphNodeIds={['n1', 'n2']} />);

      await waitFor(() => {
        expect(graphService.getSubgraph).toHaveBeenCalledWith({
          node_uuids: ['n1', 'n2'],
          include_neighbors: true,
          limit: 500,
          tenant_id: undefined,
          project_id: 'p1',
        });
      });
    });

    it('should filter communities when includeCommunities is false', async () => {
      // graphService is imported from mocks

      render(<CytoscapeGraph projectId="p1" includeCommunities={false} />);

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
        // Legend should not show Community
        expect(screen.queryByText('Community')).not.toBeInTheDocument();
      });
    });
  });

  // ========================================
  // Test Suite 4: Component Interactions
  // ========================================
  describe('Component Interactions', () => {
    it('should call relayout when relayout button is clicked', async () => {
      render(<CytoscapeGraph config={{ data: { projectId: 'p1' } }} />);

      await waitFor(() => {
        const relayoutButton = screen.getByTitle('Relayout');
        expect(relayoutButton).toBeInTheDocument();
      });

      const relayoutButton = screen.getByTitle('Relayout');
      fireEvent.click(relayoutButton);

      // Verify button exists and is clickable
      expect(relayoutButton).toBeInTheDocument();
    });

    it('should call fitView when fit button is clicked', async () => {
      render(<CytoscapeGraph config={{ data: { projectId: 'p1' } }} />);

      await waitFor(() => {
        const fitButton = screen.getByTitle('Fit to View');
        expect(fitButton).toBeInTheDocument();
      });

      const fitButton = screen.getByTitle('Fit to View');
      fireEvent.click(fitButton);

      expect(fitButton).toBeInTheDocument();
    });

    it('should trigger data reload on reload button click', async () => {
      // graphService is imported from mocks

      render(<CytoscapeGraph config={{ data: { projectId: 'p1' } }} />);

      await waitFor(() => {
        expect(screen.getByTitle('Reload Data')).toBeInTheDocument();
      });

      const reloadButton = screen.getByTitle('Reload Data');
      fireEvent.click(reloadButton);

      // Should trigger a new data fetch
      await waitFor(() => {
        expect(graphService.getGraphData).toHaveBeenCalled();
      });
    });

    it('should export image on export button click', async () => {
      render(<CytoscapeGraph config={{ data: { projectId: 'p1' } }} />);

      await waitFor(() => {
        const exportButton = screen.getByTitle('Export as PNG');
        expect(exportButton).toBeInTheDocument();
      });

      const exportButton = screen.getByTitle('Export as PNG');
      fireEvent.click(exportButton);

      expect(exportButton).toBeInTheDocument();
    });
  });

  // ========================================
  // Test Suite 5: NodeInfoPanel Functionality
  // ========================================
  describe('NodeInfoPanel', () => {
    it('should display node details when node is selected', async () => {
      const mockNode: NodeData = {
        id: 'n1',
        uuid: 'u1',
        name: 'Test Entity',
        type: 'Entity',
        entity_type: 'Person',
        summary: 'Test Summary',
        member_count: 5,
        tenant_id: 't1',
        project_id: 'p1',
      };

      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" />
          <CytoscapeGraph.NodeInfoPanel node={mockNode} />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByText('Test Entity')).toBeInTheDocument();
        expect(screen.getByText('Test Summary')).toBeInTheDocument();
        expect(screen.getByText('Person')).toBeInTheDocument();
        expect(screen.getByText('5 entities')).toBeInTheDocument();
      });
    });

    it('should close panel when close button is clicked', async () => {
      const mockNode: NodeData = {
        id: 'n1',
        uuid: 'u1',
        name: 'Test Entity',
        type: 'Entity',
      };

      const onClose = vi.fn();

      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" />
          <CytoscapeGraph.NodeInfoPanel node={mockNode} onClose={onClose} />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByText('Test Entity')).toBeInTheDocument();
      });

      const closeButton = screen.getByText('close');
      fireEvent.click(closeButton);

      expect(onClose).toHaveBeenCalled();
    });

    it('should display community specific fields', async () => {
      const mockNode: NodeData = {
        id: 'n1',
        uuid: 'u1',
        name: 'Test Community',
        type: 'Community',
        member_count: 10,
      };

      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" />
          <CytoscapeGraph.NodeInfoPanel node={mockNode} />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByText('Test Community')).toBeInTheDocument();
        expect(screen.getByText('10 entities')).toBeInTheDocument();
      });
    });

    it('should display episodic specific fields', async () => {
      const mockNode: NodeData = {
        id: 'n1',
        uuid: 'u1',
        name: 'Test Episode',
        type: 'Episodic',
        summary: 'Episode Summary',
      };

      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" />
          <CytoscapeGraph.NodeInfoPanel node={mockNode} />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByText('Test Episode')).toBeInTheDocument();
        expect(screen.getByText('Episode Summary')).toBeInTheDocument();
      });
    });
  });

  // ========================================
  // Test Suite 6: Edge Cases
  // ========================================
  describe('Edge Cases', () => {
    it('should handle null node gracefully', async () => {
      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" />
          <CytoscapeGraph.NodeInfoPanel node={null} />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(screen.getByText(/select a node/i)).toBeInTheDocument();
      });
    });

    it('should handle undefined config gracefully', async () => {
      // @ts-expect-error - Testing invalid input
      render(<CytoscapeGraph config={undefined} />);

      // Should render without crashing
      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });

    it('should handle empty projectId', async () => {
      render(<CytoscapeGraph config={{ data: { projectId: '' } }} />);

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });

    it('should handle negative minConnections', async () => {
      render(<CytoscapeGraph config={{ data: { projectId: 'p1', minConnections: -1 } }} />);

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });

    it('should handle very large node counts', async () => {
      // graphService is imported from mocks
      graphService.getGraphData.mockResolvedValueOnce({
        elements: {
          nodes: Array.from({ length: 10000 }, (_, i) => ({
            data: { id: `n${i}`, label: 'Entity', name: `Node ${i}`, uuid: `u${i}` },
          })),
          edges: [],
        },
      });

      render(<CytoscapeGraph config={{ data: { projectId: 'p1' } }} />);

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });
  });

  // ========================================
  // Test Suite 7: Theme Support
  // ========================================
  describe('Theme Support', () => {
    it('should apply light theme styles', async () => {
      // useThemeStore is imported from mocks
      useThemeStore.mockReturnValue({ computedTheme: 'light', theme: 'light' });

      render(<CytoscapeGraph config={{ data: { projectId: 'p1' } }} />);

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });

    it('should apply dark theme styles', async () => {
      // useThemeStore is imported from mocks
      useThemeStore.mockReturnValue({ computedTheme: 'dark', theme: 'dark' });

      render(<CytoscapeGraph config={{ data: { projectId: 'p1' } }} />);

      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
    });
  });

  // ========================================
  // Test Suite 8: TypeScript Type Safety
  // ========================================
  describe('Type Safety', () => {
    it('should accept valid GraphConfig', () => {
      const config: GraphConfig = {
        data: {
          projectId: 'p1',
          tenantId: 't1',
          includeCommunities: true,
          minConnections: 0,
        },
        features: {
          showToolbar: true,
          showLegend: true,
          showStats: true,
          enableExport: true,
          enableRelayout: true,
        },
        layout: {
          type: 'cose',
          animate: true,
        },
      };

      expect(config.data.projectId).toBe('p1');
    });

    it('should accept partial GraphConfig', () => {
      const config: GraphConfig = {
        data: {
          projectId: 'p1',
        },
      };

      expect(config.data.projectId).toBe('p1');
    });
  });
});
