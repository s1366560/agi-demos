export type PanelResizeConstraints = {
  min: number;
  max: number;
  default: number;
};

/**
 * Which panel edge the handle sits on: a 'trailing' handle controls a panel to
 * its left (e.g. the sidebar), so dragging right grows it; a 'leading' handle
 * controls a panel to its right (e.g. the context rail), so dragging left
 * grows it.
 */
export type PanelResizeSide = 'leading' | 'trailing';

export function clampPanelWidth(width: number, constraints: PanelResizeConstraints): number {
  if (!Number.isFinite(width)) return constraints.default;
  return Math.min(constraints.max, Math.max(constraints.min, width));
}

/**
 * Parse a persisted width. Finite values are clamped so constraint changes
 * between releases cannot strand a stored width outside the allowed range;
 * anything else counts as absent.
 */
export function parsePersistedPanelWidth(
  raw: string | null | undefined,
  constraints: PanelResizeConstraints,
): number | null {
  if (raw === null || raw === undefined) return null;
  const parsed = Number.parseFloat(raw);
  if (!Number.isFinite(parsed)) return null;
  return clampPanelWidth(parsed, constraints);
}

export function panelWidthFromDrag(
  startWidth: number,
  deltaX: number,
  side: PanelResizeSide,
  constraints: PanelResizeConstraints,
): number {
  const next = side === 'trailing' ? startWidth + deltaX : startWidth - deltaX;
  return clampPanelWidth(next, constraints);
}

export function panelWidthFromKey(
  currentWidth: number,
  key: string,
  side: PanelResizeSide,
  constraints: PanelResizeConstraints,
  step = 16,
): number | null {
  if (key !== 'ArrowLeft' && key !== 'ArrowRight') return null;
  const direction = key === 'ArrowRight' ? 1 : -1;
  const next =
    side === 'trailing' ? currentWidth + step * direction : currentWidth - step * direction;
  return clampPanelWidth(next, constraints);
}
