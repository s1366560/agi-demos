import { useParams } from 'react-router-dom';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import EdgeMapList from '../../../../pages/project/schema/EdgeMapList';
import { schemaAPI } from '../../../../services/api';
import { fireEvent, render, screen } from '../../../utils';

vi.mock('../../../../services/api', () => ({
  schemaAPI: {
    listEdgeMaps: vi.fn(),
    listEntityTypes: vi.fn(),
    listEdgeTypes: vi.fn(),
    createEdgeMap: vi.fn(),
    deleteEdgeMap: vi.fn(),
  },
}));

vi.mock('../../../../utils/confirmAction', () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useParams: vi.fn(),
  };
});

describe('EdgeMapList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useParams).mockReturnValue({ projectId: 'project-1' });
    vi.mocked(schemaAPI.listEdgeMaps).mockResolvedValue([
      {
        id: 'mapping-1',
        source_type: 'Entity',
        target_type: 'Entity',
        edge_type: 'RELATED_TO',
        source: 'manual',
        project_id: 'project-1',
      },
    ]);
    vi.mocked(schemaAPI.listEntityTypes).mockResolvedValue([]);
    vi.mocked(schemaAPI.listEdgeTypes).mockResolvedValue([
      {
        id: 'edge-1',
        name: 'RELATED_TO',
        project_id: 'project-1',
      },
    ]);
  });

  it('labels matrix add and remove icon controls', async () => {
    render(<EdgeMapList />);

    expect(
      await screen.findByRole('button', { name: 'Add mapping from Entity to Entity' })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove RELATED_TO mapping' })).toBeInTheDocument();
  });

  it('uses a real pressed button for hiding empty cells', async () => {
    render(<EdgeMapList />);

    const toggle = await screen.findByRole('button', { name: /Empty Cells/i });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-pressed', 'true');
  });

  it('filters the matrix with the search input', async () => {
    vi.mocked(schemaAPI.listEntityTypes).mockResolvedValue([
      {
        id: 'entity-1',
        name: 'Person',
        project_id: 'project-1',
      } as any,
    ]);

    render(<EdgeMapList />);

    expect(
      await screen.findByRole('button', { name: 'Add mapping from Entity to Entity' })
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('project.schema.mappings.search_placeholder'), {
      target: { value: 'Person' },
    });

    expect(
      screen.queryByRole('button', { name: 'Add mapping from Entity to Entity' })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Add mapping from Person to Person' })
    ).toBeInTheDocument();
  });

  it('does not offer a dedicated export button (export lives in Schema Overview)', async () => {
    render(<EdgeMapList />);

    await screen.findByRole('button', { name: 'Add mapping from Entity to Entity' });

    expect(screen.queryByRole('button', { name: 'Export Schema' })).not.toBeInTheDocument();
  });
});
