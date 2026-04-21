/**
 * Normalise a CyberObjective.progress value to a 0-100 percent.
 *
 * The backend domain validates progress as a fraction in [0.0, 1.0],
 * but several UI entry points (e.g. ObjectiveCreateModal's Slider)
 * send values on a 0-100 scale. This helper accepts either and always
 * returns a clamped integer percent.
 */
export function toPercent(raw: unknown): number {
  const n = typeof raw === 'number' && Number.isFinite(raw) ? raw : 0;
  const scaled = n > 1 ? n : n * 100;
  return Math.max(0, Math.min(100, Math.round(scaled)));
}
