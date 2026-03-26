import { useMemo } from 'react';

export const ADJACENT_OFFSETS = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
  [1, -1],
  [-1, 1],
] as const;

const SQRT3 = Math.sqrt(3);

export function hexToPixel(q: number, r: number, size = 40.0): { x: number; y: number } {
  const x = size * ((3.0 / 2.0) * q);
  const y = size * ((SQRT3 / 2.0) * q + SQRT3 * r);
  return { x, y };
}

function axialRound(qFrac: number, rFrac: number): { q: number; r: number } {
  const sFrac = -qFrac - rFrac;
  let qRound = Math.round(qFrac);
  let rRound = Math.round(rFrac);
  const sRound = Math.round(sFrac);

  const qDiff = Math.abs(qRound - qFrac);
  const rDiff = Math.abs(rRound - rFrac);
  const sDiff = Math.abs(sRound - sFrac);

  if (qDiff > rDiff && qDiff > sDiff) {
    qRound = -rRound - sRound;
  } else if (rDiff > sDiff) {
    rRound = -qRound - sRound;
  }

  return { q: qRound, r: rRound };
}

export function pixelToHex(x: number, y: number, size = 40.0): { q: number; r: number } {
  const qFrac = ((2.0 / 3.0) * x) / size;
  const rFrac = ((-1.0 / 3.0) * x + (SQRT3 / 3.0) * y) / size;
  return axialRound(qFrac, rFrac);
}

export function hexDistance(q1: number, r1: number, q2: number, r2: number): number {
  const dq = q2 - q1;
  const dr = r2 - r1;
  const ds = -(dq + dr);
  return Math.max(Math.abs(dq), Math.abs(dr), Math.abs(ds));
}

export function getNeighbors(q: number, r: number): Array<{ q: number; r: number }> {
  return ADJACENT_OFFSETS.map(([dq, dr]) => ({ q: q + dq, r: r + dr }));
}

export function isAdjacent(q1: number, r1: number, q2: number, r2: number): boolean {
  return hexDistance(q1, r1, q2, r2) === 1;
}

export function generateGrid(radius: number): Array<{ q: number; r: number }> {
  const cells: Array<{ q: number; r: number }> = [];
  for (let q = -radius; q <= radius; q++) {
    const r1 = Math.max(-radius, -q - radius);
    const r2 = Math.min(radius, -q + radius);
    for (let r = r1; r <= r2; r++) {
      cells.push({ q, r });
    }
  }
  return cells;
}

export function getHexCorners(
  cx: number,
  cy: number,
  size: number
): Array<{ x: number; y: number }> {
  const corners: Array<{ x: number; y: number }> = [];
  for (let i = 0; i < 6; i++) {
    const angleDeg = 60 * i;
    const angleRad = (Math.PI / 180) * angleDeg;
    corners.push({
      x: cx + size * Math.cos(angleRad),
      y: cy + size * Math.sin(angleRad),
    });
  }
  return corners;
}

export interface UseHexLayoutOptions {
  size?: number;
  gridRadius?: number;
}

export function useHexLayout({ size = 40.0, gridRadius = 5 }: UseHexLayoutOptions = {}) {
  const gridCells = useMemo(() => generateGrid(gridRadius), [gridRadius]);

  return {
    hexToPixel: (q: number, r: number) => hexToPixel(q, r, size),
    pixelToHex: (x: number, y: number) => pixelToHex(x, y, size),
    hexDistance,
    getNeighbors,
    isAdjacent,
    generateGrid,
    getHexCorners: (cx: number, cy: number) => getHexCorners(cx, cy, size),
    hexCorners: (cx: number, cy: number) => getHexCorners(cx, cy, size),
    gridCells,
    size,
    gridRadius,
  };
}
