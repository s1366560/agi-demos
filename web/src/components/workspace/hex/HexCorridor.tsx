import type { FC } from 'react';

import type { TopologyNode } from '@/types/workspace';

export interface HexCorridorProps {
  cx: number;
  cy: number;
  size: number;
  node: TopologyNode;
}

// Extracted as a separate component to allow for future interactivity,
// capacity visualizations, or animation effects on corridors without bloating HexGrid.
export const HexCorridor: FC<HexCorridorProps> = ({ cx, cy, size }) => {
  const diamondSize = size * 0.3;
  const points = [
    `${cx},${cy - diamondSize}`,
    `${cx + diamondSize},${cy}`,
    `${cx},${cy + diamondSize}`,
    `${cx - diamondSize},${cy}`,
  ].join(' ');

  return (
    <g>
      <polygon points={points} fill="#f1f5f9" stroke="#cbd5e1" strokeWidth={1.5} />
    </g>
  );
};
