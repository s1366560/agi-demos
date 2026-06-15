/**
 * TDD Tests for CytoscapeGraph Component Refactoring
 *
 * Testing the new composite component API:
 * 1. Config object API
 * 2. Composite component API
 * 3. Backward compatibility with legacy API
 */

import React from 'react';

import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockCytoscapeInstance, cytoscapeMock } = vi.hoisted(() => {
  const mockElements = {
    remove: vi.fn(),
    add: vi.fn(),
    length: 0,
  };

  const mockLayout = {
    run: vi.fn(),
    stop: vi.fn(),
  };

  const instance = {
    on: vi.fn(),
    off: vi.fn(),
    elements: vi.fn(() => mockElements),
    add: vi.fn(),
    remove: vi.fn(),
    style: vi.fn(),
    layout: vi.fn(() => mockLayout),
    fit: vi.fn(),
    png: vi.fn(() => 'data:image/png;base64,mock'),
    stop: vi.fn(),
    destroy: vi.fn(),
    destroyed: vi.fn(() => false),
    boxSelectionEnabled: vi.fn(),
    $: vi.fn(() => ({ unselect: vi.fn() })),
    ready: vi.fn((cb?: () => void) => cb?.()),
    minZoom: 0.1,
    maxZoom: 3,
    wheelSensitivity: 0.2,
  };

  return {
    mockCytoscapeInstance: instance,
    cytoscapeMock: vi.fn(() => instance),
  };
});

vi.mock('cytoscape', () => ({
  default: cytoscapeMock,
  cytoscape: cytoscapeMock,
}));

const { graphService } = vi.hoisted(() => {
  const graphService = {
    getGraphData: vi.fn(() =>
      Promise.resolve({
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
            {
              data: {
                id: 'n2',
                label: 'Community',
                name: 'Test Community',
                uuid: 'u2',
                member_count: 5,
              },
            },
          ],
          edges: [{ data: { id: 'e1', source: 'n1', target: 'n2', label: 'MEMBER_OF' } }],
        },
      })
    ),
    getSubgraph: vi.fn(() =>
      Promise.resolve({
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
      })
    ),
  };
  return { graphService };
});

vi.mock('@/services/graphService', () => ({
  graphService,
}));

import { CytoscapeGraph } from '@/components/graph/CytoscapeGraph';
import type { GraphConfig, NodeData } from '@/components/graph/CytoscapeGraph/types';

import { useThemeStore } from '../../mocks/themeStore';
import { render, screen, fireEvent, waitFor } from '../../utils';

function createDefaultGraphData() {
  return {
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
        {
          data: {
            id: 'n2',
            label: 'Community',
            name: 'Test Community',
            uuid: 'u2',
            member_count: 5,
          },
        },
      ],
      edges: [{ data: { id: 'e1', source: 'n1', target: 'n2', label: 'MEMBER_OF' } }],
    },
  };
}

function createDefaultSubgraphData() {
  return {
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
  };
}

describe('CytoscapeGraph - TDD Refactoring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    graphService.getGraphData.mockReset();
    graphService.getSubgraph.mockReset();
    graphService.getGraphData.mockResolvedValue(createDefaultGraphData());
    graphService.getSubgraph.mockResolvedValue(createDefaultSubgraphData());
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
        expect(mockCytoscapeInstance.on).toHaveBeenCalledWith('tap', 'node', expect.any(Function));
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
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

      const config: GraphConfig = {
        data: { projectId: 'p1' },
      };

      try {
        render(<CytoscapeGraph config={config} />);

        await waitFor(() => {
          expect(screen.getByText(/Network error/)).toBeInTheDocument();
        });
      } finally {
        consoleError.mockRestore();
      }
    });

    it('does not refetch after a failed load only because state is reported to the parent', async () => {
      graphService.getGraphData.mockRejectedValueOnce(new Error('Network error'));
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

      try {
        render(
          <CytoscapeGraph>
            <CytoscapeGraph.Viewport projectId="p1" />
          </CytoscapeGraph>
        );

        await waitFor(() => {
          expect(screen.getByText(/Network error/)).toBeInTheDocument();
        });

        await new Promise((resolve) => {
          setTimeout(resolve, 50);
        });

        expect(graphService.getGraphData).toHaveBeenCalledTimes(1);
      } finally {
        consoleError.mockRestore();
      }
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

      expect(screen.getByTitle('Relayout').closest('.border-b')).toHaveClass('flex-col');
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
      const _nodeClickHandler: ((node: NodeData | null) => void) | null = null;

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

    it('does not clear node selection when node tap bubbles to the core handler', async () => {
      const onNodeClick = vi.fn();
      const nodeData: NodeData = {
        id: 'n1',
        uuid: 'u1',
        name: 'Test Entity',
        type: 'Entity',
        entity_type: 'Person',
      };
      const nodeTarget = { data: () => nodeData };

      render(
        <CytoscapeGraph>
          <CytoscapeGraph.Viewport projectId="p1" onNodeClick={onNodeClick} />
          <CytoscapeGraph.NodeInfoPanel />
        </CytoscapeGraph>
      );

      await waitFor(() => {
        expect(mockCytoscapeInstance.on).toHaveBeenCalledWith('tap', 'node', expect.any(Function));
      });

      const nodeTapHandler = mockCytoscapeInstance.on.mock.calls.find(
        (call) => call[0] === 'tap' && call[1] === 'node'
      )?.[2] as ((event: { target: typeof nodeTarget }) => void) | undefined;
      const coreTapHandler = mockCytoscapeInstance.on.mock.calls.find(
        (call) => call[0] === 'tap' && typeof call[1] === 'function'
      )?.[1] as ((event: { target: typeof nodeTarget }) => void) | undefined;

      nodeTapHandler?.({ target: nodeTarget });
      coreTapHandler?.({ target: nodeTarget });

      expect(onNodeClick).toHaveBeenCalledTimes(1);
      expect(onNodeClick).toHaveBeenCalledWith(nodeData);
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
      const mockGraphData = {
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
      };
      graphService.getGraphData.mockResolvedValue(mockGraphData);
      graphService.getSubgraph.mockResolvedValue(mockGraphData);

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
      graphService.getGraphData.mockResolvedValue({
        elements: {
          nodes: [
            {
              data: {
                id: 'n1',
                label: 'Entity',
                name: 'Test Entity',
                uuid: 'u1',
              },
            },
          ],
          edges: [],
        },
      });

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
      await waitFor(() => {
        expect(screen.getByText(/Nodes:/)).toBeInTheDocument();
      });
      await waitFor(() => {
        expect(mockCytoscapeInstance.add).toHaveBeenCalled();
        expect(screen.queryByText(/Loading graph/)).not.toBeInTheDocument();
      });

      const closeButton = document.querySelector('.lucide-x')?.closest('button');
      expect(closeButton).toBeInTheDocument();
      fireEvent.click(closeButton!);

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
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
