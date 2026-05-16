import { useMemo } from 'react';
import type { FC, KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent } from 'react';

import { useTranslation } from 'react-i18next';

import { useHexLayout } from './useHexLayout';

export interface MiniMapCell {
  q: number;
  r: number;
  type: 'empty' | 'agent' | 'corridor' | 'human_seat' | 'objective';
  color?: string | undefined;
}

export interface HexMiniMapProps {
  cells: MiniMapCell[];
  viewBox: { x: number; y: number; width: number; height: number };
  containerSize: { width: number; height: number };
  onNavigate: (x: number, y: number) => void;
}

export const HexMiniMap: FC<HexMiniMapProps> = ({ cells, viewBox, onNavigate }) => {
  const { t } = useTranslation();
  const hexSize = 40.0;
  const { hexToPixel, getHexCorners } = useHexLayout({ size: hexSize });

  const { minX, minY, mapWidth, mapHeight } = useMemo(() => {
    if (cells.length === 0) return { minX: -200, minY: -200, mapWidth: 400, mapHeight: 400 };

    let min_x = Infinity;
    let max_x = -Infinity;
    let min_y = Infinity;
    let max_y = -Infinity;

    cells.forEach((cell) => {
      const { x, y } = hexToPixel(cell.q, cell.r);
      min_x = Math.min(min_x, x);
      max_x = Math.max(max_x, x);
      min_y = Math.min(min_y, y);
      max_y = Math.max(max_y, y);
    });

    const padding = hexSize * 2;
    min_x -= padding;
    max_x += padding;
    min_y -= padding;
    max_y += padding;

    return {
      minX: min_x,
      minY: min_y,
      mapWidth: max_x - min_x,
      mapHeight: max_y - min_y,
    };
  }, [cells, hexToPixel]);

  const navigateFromClientPoint = (clientX: number, clientY: number, rect: DOMRect) => {
    const clickX = clientX - rect.left;
    const clickY = clientY - rect.top;
    const scaleX = mapWidth / rect.width;
    const scaleY = mapHeight / rect.height;
    onNavigate(minX + clickX * scaleX, minY + clickY * scaleY);
  };

  const handleMapClick = (event: ReactMouseEvent<SVGSVGElement>) => {
    navigateFromClientPoint(
      event.clientX,
      event.clientY,
      event.currentTarget.getBoundingClientRect()
    );
  };

  const handleMapKeyDown = (event: ReactKeyboardEvent<SVGSVGElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    onNavigate(minX + mapWidth / 2, minY + mapHeight / 2);
  };

  return (
    <div className="absolute bottom-3 right-3 w-40 h-[120px] bg-slate-900/70 border border-white/20 rounded-lg overflow-hidden z-50">
      <svg
        width="100%"
        height="100%"
        viewBox={`${String(minX)} ${String(minY)} ${String(mapWidth)} ${String(mapHeight)}`}
        preserveAspectRatio="xMidYMid meet"
        onClick={handleMapClick}
        onKeyDown={handleMapKeyDown}
        className="cursor-pointer"
        role="button"
        tabIndex={0}
        aria-label={t('workspaceDetail.hex.miniMapAria', 'Hex Mini Map')}
      >
        <title>{t('workspaceDetail.hex.miniMapAria', 'Hex Mini Map')}</title>
        {cells.map((cell) => {
          const { x, y } = hexToPixel(cell.q, cell.r);
          const corners = getHexCorners(x, y)
            .map((p) => `${String(p.x)},${String(p.y)}`)
            .join(' ');

          let fill = 'transparent';
          if (cell.color) {
            fill = cell.color;
          } else if (cell.type === 'agent') {
            fill = '#3b82f6'; // blue
          } else if (cell.type === 'corridor') {
            fill = '#64748b'; // slate
          } else if (cell.type === 'human_seat') {
            fill = '#f59e0b'; // amber
          } else if (cell.type === 'objective') {
            fill = '#ec4899'; // pink
          } else {
            fill = '#334155'; // empty cell, slate-700
          }

          return (
            <polygon
              key={`${String(cell.q)}-${String(cell.r)}`}
              points={corners}
              fill={fill}
              stroke="rgba(255,255,255,0.1)"
              strokeWidth={2}
            />
          );
        })}
        <rect
          x={viewBox.x}
          y={viewBox.y}
          width={viewBox.width}
          height={viewBox.height}
          fill="rgba(255, 255, 255, 0.15)"
          stroke="rgba(255, 255, 255, 0.8)"
          strokeWidth={Math.max(2, mapWidth / 100)}
          style={{ pointerEvents: 'none' }}
        />
      </svg>
    </div>
  );
};
