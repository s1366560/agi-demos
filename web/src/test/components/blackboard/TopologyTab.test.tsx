import { describe, expect, it } from 'vitest';

import { TopologyTab } from '@/components/blackboard/tabs/TopologyTab';
import { render, screen } from '@/test/utils';

describe('TopologyTab', () => {
  it('marks topology as a hosted non-authoritative projection', () => {
    render(<TopologyTab topologyNodes={[]} topologyEdges={[]} topologyNodeTitles={new Map()} />);

    const boundaryBadge = screen.getByText('blackboard.topologySurfaceHint').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
  });
});
