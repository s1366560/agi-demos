import type { FC } from 'react';

import type { TopologyNode } from '@/types/workspace';

export interface HexHumanSeatProps {
  cx: number;
  cy: number;
  size: number;
  node: TopologyNode;
  userName?: string;
}

export const HexHumanSeat: FC<HexHumanSeatProps> = ({ cx, cy, size, userName }) => {
  const themeColor = '#f59e0b';
  const innerRadius = size * 0.45;
  const label = userName || 'User';
  const firstLetter = label.charAt(0).toUpperCase();

  return (
    <g>
      <circle cx={cx} cy={cy - size * 0.1} r={innerRadius} fill={themeColor} opacity={0.15} />
      <circle
        cx={cx}
        cy={cy - size * 0.1}
        r={innerRadius}
        fill="none"
        stroke={themeColor}
        strokeWidth={2}
      />
      <text
        x={cx}
        y={cy - size * 0.1}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={size * 0.4}
        fontWeight="bold"
        fill={themeColor}
        pointerEvents="none"
      >
        {firstLetter}
      </text>

      <text
        x={cx}
        y={cy + size * 0.65}
        textAnchor="middle"
        fontSize={size * 0.25}
        fill="#475569"
        pointerEvents="none"
      >
        {label.length > 10 ? `${label.substring(0, 8)}...` : label}
      </text>
    </g>
  );
};
