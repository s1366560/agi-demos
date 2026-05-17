import { describe, expect, it, vi } from 'vitest';

import { GeneList } from '@/components/workspace/genes/GeneList';
import { fireEvent, render, screen } from '@/test/utils';

import type { CyberGene } from '@/types/workspace';

const gene: CyberGene = {
  id: 'gene-1',
  workspace_id: 'workspace-1',
  name: 'Investigation Workflow',
  category: 'workflow',
  description: 'Coordinates multi-step investigations',
  version: '1.0.0',
  is_active: true,
  created_by: 'user-1',
  created_at: '2025-01-01T00:00:00Z',
};

describe('GeneList', () => {
  it('renders an empty state with a create CTA when no genes exist', () => {
    const onCreate = vi.fn();
    render(<GeneList genes={[]} onCreate={onCreate} />);

    expect(screen.getByText('workspaceDetail.genes.noGenes')).toBeInTheDocument();
    expect(screen.getByText('workspaceDetail.genes.createFirst')).toBeInTheDocument();
  });

  it('uses a semantic button for the gene actions menu', async () => {
    render(<GeneList genes={[gene]} />);

    const menuButton = screen.getByRole('button', { name: /moreActions|More actions/i });
    expect(menuButton.tagName).toBe('BUTTON');

    fireEvent.click(menuButton);

    expect(await screen.findByText('Edit')).toBeInTheDocument();
  });
});
