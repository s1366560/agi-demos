import type { FC } from 'react';

export interface HexFlowAnimationProps {
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  direction?: string;
  animated?: boolean;
}

export const HexFlowAnimation: FC<HexFlowAnimationProps> = ({
  fromX,
  fromY,
  toX,
  toY,
  direction = 'forward',
  animated = true,
}) => {
  const isBidirectional = direction === 'bidirectional';

  return (
    <g pointerEvents="none">
      <line x1={fromX} y1={fromY} x2={toX} y2={toY} stroke="#e2e8f0" strokeWidth={2} />

      <line
        x1={fromX}
        y1={fromY}
        x2={toX}
        y2={toY}
        stroke="#3b82f6"
        strokeWidth={2}
        strokeDasharray="5 5"
        className={animated ? 'hex-flow-path' : ''}
      />

      {isBidirectional && (
        <line
          x1={toX}
          y1={toY}
          x2={fromX}
          y2={fromY}
          stroke="#10b981"
          strokeWidth={2}
          strokeDasharray="5 5"
          strokeDashoffset={10}
          className={animated ? 'hex-flow-path' : ''}
          style={{ animationDirection: 'reverse' }}
        />
      )}
    </g>
  );
};
