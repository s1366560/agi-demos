import { describe, expect, it, vi } from 'vitest';

import { GeneList } from '@/components/workspace/genes/GeneList';
import { render, screen } from '@/test/utils';

describe('GeneList', () => {
  it('renders an empty state with a create CTA when no genes exist', () => {
    const onCreate = vi.fn();
    render(<GeneList genes={[]} onCreate={onCreate} />);

    expect(screen.getByText('workspaceDetail.genes.noGenes')).toBeInTheDocument();
    expect(screen.getByText('workspaceDetail.genes.createFirst')).toBeInTheDocument();
  });
});
