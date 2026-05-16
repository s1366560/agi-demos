import { useParams } from 'react-router-dom';

import { describe, it, expect, vi, beforeEach } from 'vitest';

import { MemoryGraph } from '../../../pages/project/MemoryGraph';
import { render, screen, fireEvent } from '../../utils';

// Mock CytoscapeGraph component
vi.mock('../../../components/graph/CytoscapeGraph', () => {
  const MockCytoscapeGraph = ({ children }: any) => (
    <div data-testid="cytoscape-graph">{children}</div>
  );

  MockCytoscapeGraph.Viewport = ({ onNodeClick }: any) => (
    <button
      onClick={() =>
        onNodeClick({
          id: 'e1',
          uuid: 'e1',
          name: 'Test Entity',
          type: 'Entity',
          summary: 'Test Summary',
          entity_type: 'Person',
          member_count: 5,
          connection_count: 3,
          tenant_id: 't1',
          project_id: 'p1',
        })
      }
    >
      Simulate Node Click
    </button>
  );

  return { CytoscapeGraph: MockCytoscapeGraph };
});

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useParams: vi.fn(),
  };
});

describe('MemoryGraph', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useParams as any).mockReturnValue({ projectId: 'p1' });
  });

  it('renders graph container', () => {
    render(<MemoryGraph />);
    expect(screen.getByTestId('cytoscape-graph')).toBeInTheDocument();
  });

  it('keeps the graph viewport tall enough on narrow screens', () => {
    render(<MemoryGraph />);

    expect(screen.getByTestId('memory-graph-page')).toHaveClass(
      'h-[calc(100vh-8rem)]',
      'min-h-[680px]',
      'overflow-hidden'
    );
  });

  it('shows full node details', () => {
    render(<MemoryGraph />);

    // Simulate clicking a complex node
    fireEvent.click(screen.getByText('Simulate Node Click'));

    expect(screen.getByText('Test Entity')).toBeInTheDocument();
    expect(screen.getByText('Test Summary')).toBeInTheDocument();
    expect(screen.getByText('Entity')).toBeInTheDocument();
    expect(screen.getByText('Person')).toBeInTheDocument(); // entity_type
    expect(screen.getByText('Connections')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('5 entities')).toBeInTheDocument(); // member_count
    expect(screen.getByText('Tenant: t1')).toBeInTheDocument();
    expect(screen.queryByText('Edit Node')).not.toBeInTheDocument();
  });

  it('closes details panel', () => {
    render(<MemoryGraph />);
    fireEvent.click(screen.getByText('Simulate Node Click'));
    expect(screen.getByText('Test Entity')).toBeInTheDocument();

    // Close button is a <button> containing an X icon (lucide)
    const buttons = screen.getAllByRole('button');
    const closeButton = buttons.find(
      (btn) => btn.querySelector('.lucide-x') || btn.querySelector('svg')
    );
    expect(closeButton).toBeTruthy();
    fireEvent.click(closeButton!);

    expect(screen.queryByText('Test Entity')).not.toBeInTheDocument();
  });
});
