import type { FC } from 'react';

import { toPercent } from '@/utils/objectiveProgress';

import type { CyberObjective } from '@/types/workspace';

export interface HexObjectiveProps {
  cx: number;
  cy: number;
  size: number;
  objective: CyberObjective;
}

export const HexObjective: FC<HexObjectiveProps> = ({ cx, cy, size, objective }) => {
  const themeColor = objective.obj_type === 'key_result' ? '#10b981' : '#8b5cf6';
  const innerRadius = size * 0.55;
  const progress = toPercent(objective.progress);
  
  const arcRadius = innerRadius + 4;
  const circumference = 2 * Math.PI * arcRadius;
  const strokeDashoffset = circumference - (progress / 100) * circumference;
  
  const displayName = objective.title || 'Objective';

  return (
    <g>
      <circle cx={cx} cy={cy - size * 0.1} r={innerRadius} fill={themeColor} opacity={0.15} />
      <circle cx={cx} cy={cy - size * 0.1} r={innerRadius * 0.6} fill="none" stroke={themeColor} strokeWidth={2} />
      <circle cx={cx} cy={cy - size * 0.1} r={innerRadius * 0.2} fill={themeColor} />
      
      <circle
        cx={cx}
        cy={cy - size * 0.1}
        r={arcRadius}
        fill="none"
        stroke="#e2e8f0"
        strokeWidth={3}
      />
      
      <circle
        cx={cx}
        cy={cy - size * 0.1}
        r={arcRadius}
        fill="none"
        stroke={themeColor}
        strokeWidth={3}
        strokeDasharray={circumference}
        strokeDashoffset={strokeDashoffset}
        strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy - size * 0.1})`}
      />

      <text
        x={cx}
        y={cy + size * 0.65}
        textAnchor="middle"
        fontSize={size * 0.25}
        fill="#334155"
        pointerEvents="none"
      >
        {displayName.length > 10 ? `${displayName.substring(0, 8)}...` : displayName}
      </text>
    </g>
  );
};
