import { describe, it, expect, vi, beforeEach } from 'vitest';
import { GraphProvenancePanel } from '../../../pages/project/GraphProvenancePanel';
import { graphSourceUuids, requireGraphSource } from '../../../pages/project/graphProvenance';
import { graphService } from '../../../services/graphService';
import type { GraphSnapshot } from '../../../components/graph/CytoscapeGraph/types';
import { render, screen, fireEvent, waitFor } from '../../utils';

vi.mock('../../../services/graphService', () => ({ graphService: { getSubgraph: vi.fn() } }));
const graph: GraphSnapshot = {
  nodes: [
    { id: 'source-id', uuid: 'episode-a', name: 'Same name', type: 'Episodic' },
    { id: 'entity-id', uuid: 'entity-a', name: 'Same name', type: 'Entity' },
    { id: 'community-id', name: 'Community', type: 'Community' },
  ],
  edges: [
    { id: 'mentions', source: 'source-id', target: 'entity-id', label: 'MENTIONS' },
    {
      id: 'relationship',
      source: 'entity-id',
      target: 'entity-id',
      label: 'KNOWS',
      fact: 'Recorded fact',
      episodes: ['episode-a', 'episode-b'],
    },
    { id: 'member', source: 'entity-id', target: 'community-id', label: 'BELONGS_TO' },
  ],
};
const response = (uuid = 'episode-a', project = 'p1') => ({
  elements: {
    nodes: [
      {
        data: {
          id: 'stored-id',
          uuid,
          type: 'Episodic' as const,
          label: 'Episodic',
          name: 'Same name',
          tenant_id: 't1',
          project_id: project,
          content: 'Captured original',
          memory_id: 'memory-a',
        },
      },
    ],
    edges: [],
  },
});

beforeEach(() => vi.clearAllMocks());
it('uses structural MENTIONS and episode UUIDs without inferring sources from names or membership', () => {
  expect(graphSourceUuids(graph, { kind: 'node', data: graph.nodes[1]! })).toEqual(['episode-a']);
  expect(graphSourceUuids(graph, { kind: 'edge', data: graph.edges[1]! })).toEqual([
    'episode-a',
    'episode-b',
  ]);
  expect(graphSourceUuids(graph, { kind: 'node', data: graph.nodes[2]! })).toEqual([]);
  expect(graphSourceUuids(graph, { kind: 'edge', data: graph.edges[2]! })).toEqual([]);
  expect(requireGraphSource(response(), 'episode-a', 't1', 'p1')?.content).toBe(
    'Captured original'
  );
  expect(() => requireGraphSource(response('episode-b'), 'episode-a', 't1', 'p1')).toThrow();
  expect(() => requireGraphSource(response('episode-a', 'p2'), 'episode-a', 't1', 'p1')).toThrow();
});

describe('source inspector', () => {
  const props = {
    graph,
    selection: { kind: 'edge' as const, data: graph.edges[1]! },
    tenantId: 't1',
    projectId: 'p1',
    onNode: vi.fn(),
    onEdge: vi.fn(),
  };
  it('reads an exact UUID in scope and separates captured content from the current memory link', async () => {
    vi.mocked(graphService.getSubgraph).mockResolvedValue(response());
    render(<GraphProvenancePanel {...props} />);
    expect(screen.getByText('Recorded fact')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Read source episode-a' }));
    expect(await screen.findByText('Captured original')).toBeInTheDocument();
    expect(graphService.getSubgraph).toHaveBeenCalledWith({
      node_uuids: ['episode-a'],
      include_neighbors: false,
      limit: 1,
      tenant_id: 't1',
      project_id: 'p1',
    });
    expect(screen.getByRole('link', { name: 'Open current memory' })).toHaveAttribute(
      'href',
      '/tenant/t1/project/p1/memory/memory-a'
    );
    vi.mocked(graphService.getSubgraph).mockResolvedValue({ elements: { nodes: [], edges: [] } });
    fireEvent.click(screen.getByRole('button', { name: 'Read source episode-b' }));
    expect(screen.queryByText('Captured original')).not.toBeInTheDocument();
    expect(
      await screen.findByText('This source is unavailable in the current project.')
    ).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
  it('ignores late source responses and rejects a cross-project response', async () => {
    let resolve!: (value: ReturnType<typeof response>) => void;
    vi.mocked(graphService.getSubgraph).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    vi.mocked(graphService.getSubgraph).mockResolvedValueOnce(response('episode-b', 'p2'));
    render(<GraphProvenancePanel {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Read source episode-a' }));
    fireEvent.click(screen.getByRole('button', { name: 'Read source episode-b' }));
    await screen.findByText('This source is unavailable in the current project.');
    resolve(response());
    await waitFor(() => expect(screen.queryByText('Captured original')).not.toBeInTheDocument());
  });
  it('navigates directed endpoints by element identity despite duplicate names', () => {
    render(<GraphProvenancePanel {...props} selection={{ kind: 'edge', data: graph.edges[0]! }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Same name (source-id)' }));
    expect(props.onNode).toHaveBeenCalledWith(graph.nodes[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Same name (entity-id)' }));
    expect(props.onNode).toHaveBeenLastCalledWith(graph.nodes[1]);
  });
  it.each([401, 403, 404])(
    'clears captured source and current-memory link on HTTP %s',
    async (status) => {
      vi.mocked(graphService.getSubgraph).mockResolvedValueOnce(response());
      const { unmount } = render(<GraphProvenancePanel {...props} />);
      fireEvent.click(screen.getByRole('button', { name: 'Read source episode-a' }));
      await screen.findByText('Captured original');
      vi.mocked(graphService.getSubgraph).mockRejectedValueOnce({ response: { status } });
      fireEvent.click(screen.getByRole('button', { name: 'Read source episode-a' }));
      expect(screen.queryByText('Captured original')).not.toBeInTheDocument();
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
      await screen.findByText('This source is unavailable in the current project.');
      unmount();
    }
  );
});
