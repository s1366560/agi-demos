import type { FC, ReactNode, MouseEvent, KeyboardEvent } from 'react';

export interface HexCellProps {
  q: number;
  r: number;
  size: number;
  cx: number;
  cy: number;
  selected?: boolean;
  occupied?: boolean;
  cellType?: 'empty' | 'agent' | 'corridor' | 'human_seat' | 'objective';
  onClick?: () => void;
  onContextMenu?: (e: MouseEvent<SVGGElement>) => void;
  children?: ReactNode;
}

export const HexCell: FC<HexCellProps> = ({
  q,
  r,
  cx,
  cy,
  size,
  selected = false,
  occupied = false,
  cellType = 'empty',
  onClick,
  onContextMenu,
  children,
}) => {
  const corners = [];
  for (let i = 0; i < 6; i++) {
    const angleDeg = 60 * i;
    const angleRad = (Math.PI / 180) * angleDeg;
    corners.push(`${cx + size * Math.cos(angleRad)},${cy + size * Math.sin(angleRad)}`);
  }
  const points = corners.join(' ');

  let fill = 'transparent';
  let stroke = '#e2e8f0';
  let strokeWidth = 1;
  let strokeDasharray = '4 4';

  if (selected) {
    stroke = '#1e3fae';
    strokeWidth = 3;
    strokeDasharray = 'none';
  } else if (occupied) {
    stroke = '#cbd5e1';
    strokeDasharray = 'none';
    if (cellType === 'agent') fill = '#ffffff';
    else if (cellType === 'corridor') fill = 'transparent';
    else if (cellType === 'human_seat') fill = '#fffbeb';
    else if (cellType === 'objective') fill = '#faf5ff';
  }

  const handleKeyDown = (e: KeyboardEvent<SVGGElement>) => {
    if ((e.key === 'Enter' || e.key === ' ') && onClick) {
      e.preventDefault();
      onClick();
    }
  };

  return (
    <g
      onClick={onClick}
      onKeyDown={handleKeyDown}
      onContextMenu={onContextMenu}
      role="button"
      tabIndex={onClick ? 0 : undefined}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
      className="hover:opacity-80 transition-opacity duration-200"
      aria-label={`Hex cell at q:${q}, r:${r}`}
    >
      <polygon
        points={points}
        fill={fill}
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeDasharray={strokeDasharray}
      />
      {children}
    </g>
  );
};
