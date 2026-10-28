import type { McpAppGuestRect } from './mcpAppGuestProtocol';

function valid(rect: McpAppGuestRect): boolean {
  return (
    [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) &&
    rect.width > 0 &&
    rect.height > 0
  );
}

export function intersectGuestRects(
  a: McpAppGuestRect,
  b: McpAppGuestRect,
): McpAppGuestRect | null {
  if (!valid(a) || !valid(b)) return null;
  const x = Math.max(a.x, b.x);
  const y = Math.max(a.y, b.y);
  const width = Math.min(a.x + a.width, b.x + b.width) - x;
  const height = Math.min(a.y + a.height, b.y + b.height) - y;
  return width > 0 && height > 0 ? { x, y, width, height } : null;
}

/** Rectangle subtraction is geometric: native child views must never cover host controls. */
export function computeMcpAppGuestBounds(
  slot: McpAppGuestRect,
  viewport: McpAppGuestRect,
  occluders: readonly McpAppGuestRect[],
): McpAppGuestRect | null {
  const available = intersectGuestRects(slot, viewport);
  if (!available || occluders.length > 64 || occluders.some((rect) => !valid(rect))) return null;
  let candidates = [available];
  for (const blocker of occluders) {
    const reserved = {
      x: blocker.x - 8,
      y: blocker.y - 8,
      width: blocker.width + 16,
      height: blocker.height + 16,
    };
    const next = new Map<string, McpAppGuestRect>();
    for (const candidate of candidates) {
      const overlap = intersectGuestRects(candidate, reserved);
      const pieces = overlap
        ? [
            { ...candidate, height: overlap.y - candidate.y },
            {
              ...candidate,
              y: overlap.y + overlap.height,
              height: candidate.y + candidate.height - overlap.y - overlap.height,
            },
            { ...candidate, width: overlap.x - candidate.x },
            {
              ...candidate,
              x: overlap.x + overlap.width,
              width: candidate.x + candidate.width - overlap.x - overlap.width,
            },
          ]
        : [candidate];
      for (const piece of pieces) if (valid(piece)) next.set(JSON.stringify(piece), piece);
    }
    if (next.size > 256) return null;
    candidates = [...next.values()];
  }
  candidates.sort((a, b) => b.width * b.height - a.width * a.height || a.y - b.y || a.x - b.x);
  const best = candidates[0];
  if (!best) return null;
  // Rounding inwards preserves the exclusion even at fractional zoom/scroll positions.
  const x = Math.ceil(best.x);
  const y = Math.ceil(best.y);
  const result = {
    x,
    y,
    width: Math.floor(best.x + best.width) - x,
    height: Math.floor(best.y + best.height) - y,
  };
  return valid(result) ? result : null;
}
