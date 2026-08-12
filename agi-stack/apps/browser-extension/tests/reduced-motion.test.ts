import { describe, expect, it } from 'vitest';
import { CursorAnimator } from '../src/cursor/engine';
import { shouldAnimateCursor } from '../src/cursor/motion-preference';

describe('reduced-motion cursor', () => {
  it('teleports, completes the arrival handshake once, and becomes idle', () => {
    const animator = new CursorAnimator({ width: 1280, height: 800 }, { x: 10, y: 10 });

    animator.moveTo({ x: 900, y: 500 }, shouldAnimateCursor(true, true));
    animator.update(0);

    expect(animator.position).toEqual({ x: 900, y: 500 });
    expect(animator.consumeArrived()).toBe(true);
    expect(animator.consumeArrived()).toBe(false);
    expect(animator.needsRender).toBe(false);
  });

  it('keeps requested animation only when reduced motion is not active', () => {
    expect(shouldAnimateCursor(true, false)).toBe(true);
    expect(shouldAnimateCursor(true, true)).toBe(false);
    expect(shouldAnimateCursor(false, false)).toBe(false);
  });
});
