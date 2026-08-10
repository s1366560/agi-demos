import { describe, expect, it } from 'vitest';
import {
  ARRIVAL_DISTANCE_PX,
  CursorAnimator,
  MAX_RESPONSE_S,
  MIN_RESPONSE_S,
  REST_ROTATION_DEG,
  SCOOT_MAX_DISTANCE_PX,
  STRETCH_MIN,
  Spring,
  generateCandidates,
  planPath,
  responseForPath,
  type CursorPath,
} from '../src/cursor/engine';

const VIEWPORT = { width: 1280, height: 800 };

function run(animator: CursorAnimator, seconds: number, dt = 1 / 60) {
  let pose = animator.update(0);
  const steps = Math.ceil(seconds / dt);
  for (let i = 0; i < steps; i++) pose = animator.update(dt);
  return pose;
}

describe('Spring', () => {
  it('settles on the target with near-zero velocity', () => {
    const spring = new Spring(0, 0.3, 0.9);
    spring.target = 100;
    for (let i = 0; i < 240 * 3; i++) spring.update(1 / 240);
    expect(Math.abs(spring.value - 100)).toBeLessThan(0.5);
    expect(Math.abs(spring.velocity)).toBeLessThan(1);
  });

  it('does not overshoot when critically damped', () => {
    const spring = new Spring(0, 0.3, 1);
    spring.target = 50;
    let max = 0;
    for (let i = 0; i < 240 * 3; i++) {
      spring.update(1 / 240);
      max = Math.max(max, spring.value);
    }
    expect(max).toBeLessThanOrEqual(50.5);
  });
});

describe('path planning', () => {
  it('scoots at or below 196px, plans a bezier path beyond it', () => {
    expect(planPath({ x: 0, y: 0 }, { x: SCOOT_MAX_DISTANCE_PX, y: 0 }, VIEWPORT)).toBeNull();
    expect(planPath({ x: 0, y: 0 }, { x: SCOOT_MAX_DISTANCE_PX + 1, y: 0 }, VIEWPORT)).not.toBeNull();
    // Diagonal with length just under the threshold also scoots.
    const d = (SCOOT_MAX_DISTANCE_PX - 1) / Math.SQRT2;
    expect(planPath({ x: 0, y: 0 }, { x: d, y: d }, VIEWPORT)).toBeNull();
  });

  it('generates exactly 20 candidates (2 plain + 18 arcs)', () => {
    const candidates = generateCandidates({ x: 100, y: 100 }, { x: 900, y: 600 }, VIEWPORT);
    expect(candidates).toHaveLength(20);
    expect(candidates.filter((c) => !c.hasArc)).toHaveLength(2);
    expect(candidates.filter((c) => c.hasArc)).toHaveLength(18);
  });

  it('selects the lowest-scoring candidate', () => {
    const from = { x: 100, y: 400 };
    const to = { x: 1100, y: 400 };
    const best = planPath(from, to, VIEWPORT);
    expect(best).not.toBeNull();
    const candidates = generateCandidates(from, to, VIEWPORT);
    const minScore = Math.min(...candidates.map((c) => c.score));
    expect(best?.score).toBe(minScore);
  });

  it('prefers a path that stays inside the viewport (+20px margin)', () => {
    // A horizontal move near the top edge: any upward arc leaves the viewport.
    const best = planPath({ x: 100, y: 5 }, { x: 1000, y: 5 }, VIEWPORT);
    expect(best).not.toBeNull();
    expect(best?.metrics.overshoot).toBe(0);
    expect(best?.hasArc).toBe(false);
  });

  it('clamps the progress-spring response to [0.12, 2.2]', () => {
    const fake = (length: number, totalTurn: number): CursorPath => ({
      segments: [],
      hasArc: false,
      metrics: { length, totalTurn, overshoot: 0, angleChangeEnergy: 0, maxAngleChange: 0, backtrack: 0 },
      score: 0,
      samples: [],
    });
    expect(responseForPath(fake(1, 0))).toBe(MIN_RESPONSE_S);
    expect(responseForPath(fake(100_000, 500))).toBe(MAX_RESPONSE_S);
    const mid = responseForPath(fake(600, 0.5));
    expect(mid).toBeGreaterThan(MIN_RESPONSE_S);
    expect(mid).toBeLessThan(MAX_RESPONSE_S);
  });
});

describe('CursorAnimator', () => {
  it('animates to the target and reports arrival exactly once', () => {
    const animator = new CursorAnimator(VIEWPORT, { x: 0, y: 0 });
    animator.moveTo({ x: 800, y: 500 }, true);
    let arrived = 0;
    let pose = animator.update(0);
    for (let i = 0; i < 60 * 8 && arrived === 0; i++) {
      pose = animator.update(1 / 60);
      if (animator.consumeArrived()) arrived++;
    }
    expect(arrived).toBe(1);
    expect(animator.consumeArrived()).toBe(false); // consumed exactly once
    expect(Math.hypot(pose.x - 800, pose.y - 500)).toBeLessThanOrEqual(ARRIVAL_DISTANCE_PX);
    expect(pose.visible).toBe(true);
  });

  it('teleports when animateMovement is false and arrives immediately', () => {
    const animator = new CursorAnimator(VIEWPORT, { x: 5, y: 5 });
    animator.moveTo({ x: 700, y: 300 }, false);
    const pose = animator.update(1 / 60);
    expect(pose.x).toBe(700);
    expect(pose.y).toBe(300);
    expect(animator.consumeArrived()).toBe(true);
  });

  it('scoots short moves and still converges', () => {
    const animator = new CursorAnimator(VIEWPORT, { x: 100, y: 100 });
    animator.moveTo({ x: 100 + SCOOT_MAX_DISTANCE_PX, y: 100 }, true);
    const pose = run(animator, 3);
    expect(animator.consumeArrived()).toBe(true);
    expect(Math.hypot(pose.x - 296, pose.y - 100)).toBeLessThanOrEqual(ARRIVAL_DISTANCE_PX);
  });

  it('keeps the stretch within [0.65, 1] during fast movement', () => {
    const animator = new CursorAnimator(VIEWPORT, { x: 0, y: 0 });
    animator.moveTo({ x: 1200, y: 700 }, true);
    for (let i = 0; i < 30; i++) {
      const pose = animator.update(1 / 60);
      expect(pose.stretch).toBeGreaterThanOrEqual(STRETCH_MIN);
      expect(pose.stretch).toBeLessThanOrEqual(1);
    }
  });

  it('rests at the -44 degree orientation after settling', () => {
    const animator = new CursorAnimator(VIEWPORT, { x: 0, y: 0 });
    animator.moveTo({ x: 600, y: 400 }, true);
    const pose = run(animator, 6); // arrival + wobble (1.4s) + settle
    expect(Math.abs(pose.rotationDeg - REST_ROTATION_DEG)).toBeLessThan(2);
  });

  it('hides via the visibility spring', () => {
    const animator = new CursorAnimator(VIEWPORT, { x: 0, y: 0 });
    animator.moveTo({ x: 50, y: 50 }, false);
    run(animator, 1);
    animator.hide();
    const pose = run(animator, 1);
    expect(pose.visible).toBe(false);
    expect(pose.opacity).toBeLessThanOrEqual(0.01);
  });
});
