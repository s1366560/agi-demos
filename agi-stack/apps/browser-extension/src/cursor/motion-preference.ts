export const CURSOR_REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

export function shouldAnimateCursor(
  animateMovement: boolean,
  reducedMotion: boolean,
): boolean {
  return animateMovement && !reducedMotion;
}
