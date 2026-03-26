import type { FC } from 'react';

import type { WorkspaceAgent } from '@/types/workspace';

export interface HexAgentProps {
  agent: WorkspaceAgent;
  cx: number;
  cy: number;
  size: number;
}

export const HexAgent: FC<HexAgentProps> = ({ agent, cx, cy, size }) => {
  const themeColor = agent.theme_color || '#1e3fae';
  const innerRadius = size * 0.55;
  const displayName = agent.display_name || agent.agent_id || 'Unknown';
  const firstLetter = displayName.charAt(0).toUpperCase();

  let statusColor = '#94a3b8';
  if (agent.status === 'busy') statusColor = '#3b82f6';
  else if (agent.status === 'error') statusColor = '#ef4444';
  else if (agent.is_active) statusColor = '#22c55e';

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
        fontSize={size * 0.5}
        fontWeight="bold"
        fill={themeColor}
        pointerEvents="none"
      >
        {firstLetter}
      </text>

      <circle
        cx={cx + innerRadius * 0.7}
        cy={cy - size * 0.1 + innerRadius * 0.7}
        r={size * 0.15}
        fill={statusColor}
        stroke="#ffffff"
        strokeWidth={2}
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
