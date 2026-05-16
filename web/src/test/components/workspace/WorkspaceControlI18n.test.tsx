import { describe, expect, it, vi } from 'vitest';

import { GeneAssignModal } from '@/components/workspace/genes/GeneAssignModal';
import { HexContextMenu } from '@/components/workspace/hex/HexContextMenu';
import { ObjectiveCreateModal } from '@/components/workspace/objectives/ObjectiveCreateModal';
import type { CyberGene } from '@/types/workspace';

import { fireEvent, render, screen } from '../../utils';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: string | ({ defaultValue?: string } & Record<string, unknown>)) => {
      const fallback = typeof options === 'string' ? options : (options?.defaultValue ?? _key);
      if (typeof options === 'string') {
        return fallback;
      }
      return fallback.replace(/\{\{(\w+)\}\}/g, (_match, token: string) =>
        String(options?.[token] ?? '')
      );
    },
    i18n: { language: 'en-US', changeLanguage: vi.fn() },
  }),
}));

describe('workspace localized controls', () => {
  it('renders gene assignment modal copy through translation fallbacks', async () => {
    render(
      <GeneAssignModal
        open
        agentName="Planner"
        availableGenes={[]}
        assignedGeneIds={[]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(await screen.findByText('Assign Genes to Planner')).toBeInTheDocument();
    expect(screen.getByText('No active genes available in this workspace.')).toBeInTheDocument();
    expect(screen.getByText('Save Assignments')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('renders objective modal labels and controls through translation fallbacks', async () => {
    render(
      <ObjectiveCreateModal open onClose={vi.fn()} onSubmit={vi.fn()} parentObjectives={[]} />
    );

    expect(await screen.findByText('Create Objective/Key Result')).toBeInTheDocument();
    expect(screen.getByText('Title')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('E.g., Increase Q3 Revenue')).toBeInTheDocument();
    expect(screen.getByText('Description')).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Add some details about this objective...')
    ).toBeInTheDocument();
    expect(screen.getByText('Type')).toBeInTheDocument();
    expect(screen.getByText('Progress (%)')).toBeInTheDocument();
    expect(screen.getByText('Create')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('renders hex menu labels and dispatches the selected action', () => {
    const onAction = vi.fn();
    const onClose = vi.fn();

    render(<HexContextMenu q={1} r={-2} x={12} y={24} onClose={onClose} onAction={onAction} />);

    expect(screen.getByRole('menu', { name: 'Hex cell actions' })).toBeInTheDocument();
    expect(screen.getByText('Hex (1, -2)')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'View Details' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Add Corridor' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('menuitem', { name: 'Assign Agent' }));

    expect(onAction).toHaveBeenCalledWith('assign_agent', 1, -2);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders gene options without replacing domain-provided labels', async () => {
    const gene: CyberGene = {
      id: 'gene-1',
      workspace_id: 'workspace-1',
      name: 'Research Boost',
      category: 'knowledge',
      version: '1.0.0',
      is_active: true,
      created_by: 'user-1',
      created_at: '2024-01-01T00:00:00Z',
    };

    render(
      <GeneAssignModal
        open
        agentName="Planner"
        availableGenes={[gene]}
        assignedGeneIds={[]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(await screen.findByText('Research Boost')).toBeInTheDocument();
    expect(screen.getByText('knowledge')).toBeInTheDocument();
    expect(screen.getByText('v1.0.0')).toBeInTheDocument();
  });
});
