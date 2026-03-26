import type { FC } from 'react';

import { Tooltip } from 'antd';

export interface HexTooltipProps {
  x: number;
  y: number;
  visible: boolean;
  title: string;
  details?: Record<string, string>;
  onClose?: () => void;
}

export const HexTooltip: FC<HexTooltipProps> = ({ x, y, visible, title, details }) => {
  if (!visible) return null;

  const content = (
    <div className="flex flex-col gap-1 text-sm">
      <div className="font-bold border-b border-gray-600 pb-1 mb-1">{title}</div>
      {details &&
        Object.entries(details).map(([key, value]) => (
          <div key={key} className="flex justify-between gap-4">
            <span className="text-gray-400">{key}:</span>
            <span className="font-mono">{value}</span>
          </div>
        ))}
    </div>
  );

  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        pointerEvents: 'none',
        zIndex: 1000,
      }}
    >
      <Tooltip title={content} open={visible} placement="top">
        <div style={{ width: 1, height: 1 }} />
      </Tooltip>
    </div>
  );
};
