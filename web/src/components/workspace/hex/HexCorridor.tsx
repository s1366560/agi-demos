import type { FC } from 'react';

import type { TopologyNode } from '@/types/workspace';

export interface HexCorridorProps {
  cx: number;
  cy: number;
  size: number;
  node: TopologyNode;
}

// Extracted so corridor drawing stays out of HexGrid's selection logic.
export const HexCorridor: FC<HexCorridorProps> = ({ cx, cy, size }) => {
  const diamondSize = size * 0.3;
  const points = [
    `${String(cx)},${String(cy - diamondSize)}`,
    `${String(cx + diamondSize)},${String(cy)}`,
    `${String(cx)},${String(cy + diamondSize)}`,
    `${String(cx - diamondSize)},${String(cy)}`,
  ].join(' ');

  return (
    <g>
      <polygon points={points} fill="#f1f5f9" stroke="#cbd5e1" strokeWidth={1.5} />
    </g>
  );
};
