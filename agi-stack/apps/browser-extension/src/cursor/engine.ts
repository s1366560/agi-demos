/**
 * Virtual-cursor animation engine. Framework-free, DOM-free: the same module
 * runs inside the cursor content script and under Vitest.
 *
 * Semantics (design: docs/design/browser-extension-bridge.md §2.7):
 * - SwiftUI-style springs {response, dampingFraction}, semi-implicit Euler,
 *   fixed 240Hz substeps, driven externally (rAF in the page).
 * - Short moves (<= 196px) "scoot": direct spring with a sin(pi*progress)
 *   dip + tilt. Long moves follow a planned bezier path whose progress is
 *   itself a spring; the position spring trails the path point.
 * - Arrival: progress >= .999 AND within 0.85px AND speed <= 12px/s.
 * - Resting orientation -44deg; speed-adaptive stretch along the heading;
 *   a subtle rotation wobble plays for 1.4s after arrival.
 */

export interface Vec2 {
  x: number;
  y: number;
}

export interface Viewport {
  width: number;
  height: number;
}

export const SCOOT_MAX_DISTANCE_PX = 196;
export const SUBSTEPS_PER_SECOND = 240;
export const ARRIVAL_PROGRESS = 0.999;
export const ARRIVAL_DISTANCE_PX = 0.85;
export const ARRIVAL_SPEED_PX_S = 12;
export const REST_ROTATION_DEG = -44;
export const WOBBLE_DURATION_S = 1.4;
export const WOBBLE_AMPLITUDE_DEG = 12.5;
export const STRETCH_SPEED_DIVISOR = 5500;
export const STRETCH_MIN = 0.65;

export const ARC_SCALES = [0.55, 0.8, 1.05] as const;
export const HANDLE_SCALES = [0.65, 1, 1.35] as const;
export const SAMPLES_PER_SEGMENT = 24;
export const VIEWPORT_MARGIN_PX = 20;
export const MIN_RESPONSE_S = 0.12;
export const MAX_RESPONSE_S = 2.2;

export const SCORE_WEIGHTS = {
  overshoot: 320,
  angleChangeEnergy: 140,
  maxAngleChange: 180,
  totalTurn: 18,
  backtrack: 90,
  arcPenalty: 45,
} as const;

const DEG = 180 / Math.PI;

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function distance(a: Vec2, b: Vec2): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

/**
 * Critically/under-damped spring, semi-implicit Euler at fixed substeps.
 * `response` is the SwiftUI-style duration knob (seconds); `dampingFraction`
 * is the damping ratio (1 = critically damped, <1 = bouncy).
 */
export class Spring {
  value: number;
  velocity = 0;
  target: number;

  constructor(
    initial: number,
    public response: number,
    public dampingFraction: number,
  ) {
    this.value = initial;
    this.target = initial;
  }

  /** Advance by `dt` seconds in fixed 1/240s substeps. */
  update(dt: number): void {
    if (this.response <= 0) {
      this.value = this.target;
      this.velocity = 0;
      return;
    }
    const step = 1 / SUBSTEPS_PER_SECOND;
    let remaining = dt;
    const omega = (2 * Math.PI) / this.response;
    const damping = 2 * this.dampingFraction * omega;
    while (remaining > 1e-12) {
      const h = Math.min(step, remaining);
      const acceleration = -omega * omega * (this.value - this.target) - damping * this.velocity;
      this.velocity += acceleration * h;
      this.value += this.velocity * h;
      remaining -= h;
    }
  }

  snap(target: number): void {
    this.value = target;
    this.target = target;
    this.velocity = 0;
  }

  get speed(): number {
    return Math.abs(this.velocity);
  }
}

// ---------------------------------------------------------------------------
// Bezier paths
// ---------------------------------------------------------------------------

export interface CubicSegment {
  p0: Vec2;
  p1: Vec2;
  p2: Vec2;
  p3: Vec2;
}

function sampleCubic(seg: CubicSegment, t: number): Vec2 {
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const d = t * t * t;
  return {
    x: a * seg.p0.x + b * seg.p1.x + c * seg.p2.x + d * seg.p3.x,
    y: a * seg.p0.y + b * seg.p1.y + c * seg.p2.y + d * seg.p3.y,
  };
}

export interface PathMetrics {
  length: number;
  /** Fraction of samples outside the viewport inflated by VIEWPORT_MARGIN_PX. */
  overshoot: number;
  /** Sum of squared heading changes between consecutive samples (rad^2). */
  angleChangeEnergy: number;
  /** Largest single heading change (rad). */
  maxAngleChange: number;
  /** Sum of absolute heading changes (rad). */
  totalTurn: number;
  /** Fraction of steps moving against the from→to chord. */
  backtrack: number;
}

export interface CursorPath {
  segments: CubicSegment[];
  hasArc: boolean;
  metrics: PathMetrics;
  score: number;
  /** Arc-length parameterized sample table for pointAt/tangentAt. */
  samples: Vec2[];
}

function sampleSegments(segments: CubicSegment[]): Vec2[] {
  const points: Vec2[] = [];
  for (const seg of segments) {
    for (let i = 0; i < SAMPLES_PER_SEGMENT; i++) {
      points.push(sampleCubic(seg, i / SAMPLES_PER_SEGMENT));
    }
  }
  const last = segments[segments.length - 1];
  if (last) points.push({ ...last.p3 });
  return points;
}

function measurePath(
  segments: CubicSegment[],
  hasArc: boolean,
  from: Vec2,
  to: Vec2,
  viewport: Viewport,
): CursorPath {
  const samples = sampleSegments(segments);
  const chord = { x: to.x - from.x, y: to.y - from.y };
  let length = 0;
  let outside = 0;
  let backtrackSteps = 0;
  let angleChangeEnergy = 0;
  let maxAngleChange = 0;
  let totalTurn = 0;
  let previousAngle: number | undefined;
  for (let i = 1; i < samples.length; i++) {
    const current = samples[i];
    const previous = samples[i - 1];
    if (!current || !previous) continue;
    const step = { x: current.x - previous.x, y: current.y - previous.y };
    const stepLength = Math.hypot(step.x, step.y);
    length += stepLength;
    if (stepLength < 1e-9) continue;
    if (step.x * chord.x + step.y * chord.y < 0) backtrackSteps++;
    const angle = Math.atan2(step.y, step.x);
    if (previousAngle !== undefined) {
      let turn = Math.abs(angle - previousAngle);
      if (turn > Math.PI) turn = 2 * Math.PI - turn;
      angleChangeEnergy += turn * turn;
      totalTurn += turn;
      if (turn > maxAngleChange) maxAngleChange = turn;
    }
    previousAngle = angle;
  }
  const minX = -VIEWPORT_MARGIN_PX;
  const minY = -VIEWPORT_MARGIN_PX;
  const maxX = viewport.width + VIEWPORT_MARGIN_PX;
  const maxY = viewport.height + VIEWPORT_MARGIN_PX;
  for (const point of samples) {
    if (point.x < minX || point.x > maxX || point.y < minY || point.y > maxY) outside++;
  }
  const stepCount = samples.length - 1;
  const metrics: PathMetrics = {
    length,
    overshoot: samples.length === 0 ? 0 : outside / samples.length,
    angleChangeEnergy,
    maxAngleChange,
    totalTurn,
    backtrack: stepCount === 0 ? 0 : backtrackSteps / stepCount,
  };
  const score =
    metrics.length +
    metrics.overshoot * SCORE_WEIGHTS.overshoot +
    metrics.angleChangeEnergy * SCORE_WEIGHTS.angleChangeEnergy +
    metrics.maxAngleChange * SCORE_WEIGHTS.maxAngleChange +
    metrics.totalTurn * SCORE_WEIGHTS.totalTurn +
    metrics.backtrack * SCORE_WEIGHTS.backtrack +
    (hasArc ? SCORE_WEIGHTS.arcPenalty : 0);
  return { segments, hasArc, metrics, score, samples };
}

function plainCubic(from: Vec2, to: Vec2, first: number, second: number): CubicSegment {
  return {
    p0: from,
    p1: { x: from.x + (to.x - from.x) * first, y: from.y + (to.y - from.y) * first },
    p2: { x: from.x + (to.x - from.x) * second, y: from.y + (to.y - from.y) * second },
    p3: to,
  };
}

/** Two-segment cubic arc bowing `arcScale * distance/2` off the chord. */
function twoSegmentArc(
  from: Vec2,
  to: Vec2,
  arcScale: number,
  handleScale: number,
  normalSign: 1 | -1,
): CubicSegment[] {
  const chord = { x: to.x - from.x, y: to.y - from.y };
  const length = Math.hypot(chord.x, chord.y) || 1;
  const normal = { x: (-chord.y / length) * normalSign, y: (chord.x / length) * normalSign };
  const mid: Vec2 = {
    x: (from.x + to.x) / 2 + normal.x * (length / 2) * arcScale,
    y: (from.y + to.y) / 2 + normal.y * (length / 2) * arcScale,
  };
  const handle = (a: Vec2, b: Vec2, t: number): Vec2 => ({
    x: a.x + (b.x - a.x) * t * handleScale,
    y: a.y + (b.y - a.y) * t * handleScale,
  });
  return [
    { p0: from, p1: handle(from, mid, 1 / 3), p2: handle(mid, from, 1 / 3), p3: mid },
    { p0: mid, p1: handle(mid, to, 1 / 3), p2: handle(to, mid, 1 / 3), p3: to },
  ];
}

/** The 20 scored candidates: 2 plain cubics + 3x3x2 two-segment arcs. */
export function generateCandidates(from: Vec2, to: Vec2, viewport: Viewport): CursorPath[] {
  const candidates: CursorPath[] = [
    measurePath([plainCubic(from, to, 1 / 3, 2 / 3)], false, from, to, viewport),
    measurePath([plainCubic(from, to, 0.25, 0.75)], false, from, to, viewport),
  ];
  for (const arcScale of ARC_SCALES) {
    for (const handleScale of HANDLE_SCALES) {
      for (const normalSign of [1, -1] as const) {
        candidates.push(
          measurePath(twoSegmentArc(from, to, arcScale, handleScale, normalSign), true, from, to, viewport),
        );
      }
    }
  }
  return candidates;
}

export function planPath(from: Vec2, to: Vec2, viewport: Viewport): CursorPath | null {
  if (distance(from, to) <= SCOOT_MAX_DISTANCE_PX) return null; // scoot instead
  const candidates = generateCandidates(from, to, viewport);
  let best: CursorPath | undefined;
  for (const candidate of candidates) {
    if (best === undefined || candidate.score < best.score) best = candidate;
  }
  return best ?? null;
}

/** Blend path metrics into the progress-spring response, clamped. */
export function responseForPath(path: CursorPath): number {
  const response = 0.1 + path.metrics.length / 1500 + path.metrics.totalTurn * 0.08;
  return clamp(response, MIN_RESPONSE_S, MAX_RESPONSE_S);
}

function pointAt(path: CursorPath, t: number): Vec2 {
  const clamped = clamp(t, 0, 1);
  const index = clamped * (path.samples.length - 1);
  const low = Math.floor(index);
  const high = Math.min(path.samples.length - 1, low + 1);
  const frac = index - low;
  const a = path.samples[low];
  const b = path.samples[high];
  if (!a || !b) return { x: 0, y: 0 };
  return {
    x: a.x + (b.x - a.x) * frac,
    y: a.y + (b.y - a.y) * frac,
  };
}

// ---------------------------------------------------------------------------
// Animator
// ---------------------------------------------------------------------------

export interface CursorPose {
  x: number;
  y: number;
  rotationDeg: number;
  /** Speed-adaptive squash factor along the heading, in [0.65, 1]. */
  stretch: number;
  /** Heading the stretch is applied along (deg). */
  headingDeg: number;
  opacity: number;
  visible: boolean;
}

export type MoveKind = 'teleport' | 'scoot' | 'path';

interface ActiveMove {
  kind: MoveKind;
  from: Vec2;
  to: Vec2;
  path: CursorPath | null;
}

const POSITION_RESPONSE_FACTOR = 1.2; // position spring trails the path point
const ROTATION_RESPONSE_S = 0.28;
const VISIBILITY_RESPONSE_S = 0.16;
const DAMPING = 0.86;
const HEADING_SPEED_THRESHOLD_PX_S = 30;
const SCOOT_DIP_PX = 5;
const SCOOT_TILT_DEG = 9;

export class CursorAnimator {
  private posX: Spring;
  private posY: Spring;
  private progress = new Spring(0, MIN_RESPONSE_S, 1);
  private rotation = new Spring(REST_ROTATION_DEG, ROTATION_RESPONSE_S, DAMPING);
  private visibility = new Spring(0, VISIBILITY_RESPONSE_S, 1);
  private move: ActiveMove | null = null;
  private arrivedPending = false;
  private wobbleTime = WOBBLE_DURATION_S;
  private headingDeg = REST_ROTATION_DEG;

  constructor(
    private viewport: Viewport,
    start: Vec2 = { x: 0, y: 0 },
  ) {
    this.posX = new Spring(start.x, MIN_RESPONSE_S, DAMPING);
    this.posY = new Spring(start.y, MIN_RESPONSE_S, DAMPING);
  }

  get position(): Vec2 {
    return { x: this.posX.value, y: this.posY.value };
  }

  setViewport(viewport: Viewport): void {
    this.viewport = viewport;
  }

  get isMoving(): boolean {
    return this.move !== null;
  }

  /** Whether another rAF tick is worthwhile (anything still in flight). */
  get needsRender(): boolean {
    return (
      this.move !== null ||
      this.arrivedPending ||
      this.wobbleTime < WOBBLE_DURATION_S ||
      Math.abs(this.visibility.value - this.visibility.target) > 0.004 ||
      Math.abs(this.rotation.value - this.rotation.target) > 0.5
    );
  }

  moveTo(to: Vec2, animateMovement: boolean): void {
    const from = this.position;
    this.wobbleTime = WOBBLE_DURATION_S;
    this.visibility.target = 1;
    if (!animateMovement) {
      this.move = { kind: 'teleport', from, to, path: null };
      this.posX.snap(to.x);
      this.posY.snap(to.y);
      this.rotation.snap(REST_ROTATION_DEG);
      this.visibility.snap(1);
      this.arrivedPending = true;
      this.move = null;
      this.wobbleTime = 0;
      return;
    }
    const path = planPath(from, to, this.viewport);
    if (path === null) {
      // Scoot: direct spring with a dip + tilt keyed off covered distance.
      const d = distance(from, to);
      const response = clamp(0.09 + d / 900, MIN_RESPONSE_S, 0.5);
      this.posX.response = response;
      this.posY.response = response;
      this.move = { kind: 'scoot', from, to, path: null };
    } else {
      const response = responseForPath(path);
      this.progress.snap(0);
      this.progress.response = response;
      this.progress.target = 1;
      this.posX.response = clamp(response * POSITION_RESPONSE_FACTOR, MIN_RESPONSE_S, MAX_RESPONSE_S);
      this.posY.response = this.posX.response;
      this.move = { kind: 'path', from, to, path };
    }
    this.posX.target = to.x;
    this.posY.target = to.y;
  }

  hide(): void {
    this.move = null;
    this.visibility.target = 0;
  }

  /** True exactly once after each arrival until consumed. */
  consumeArrived(): boolean {
    const pending = this.arrivedPending;
    this.arrivedPending = false;
    return pending;
  }

  update(dt: number): CursorPose {
    const move = this.move;
    if (move !== null) {
      if (move.kind === 'path' && move.path !== null) {
        this.progress.update(dt);
        const point = pointAt(move.path, this.progress.value);
        this.posX.target = point.x;
        this.posY.target = point.y;
      }
      this.posX.update(dt);
      this.posY.update(dt);
      this.checkArrival(move);
    } else {
      this.posX.update(dt);
      this.posY.update(dt);
    }

    const speed = Math.hypot(this.posX.velocity, this.posY.velocity);
    if (speed > HEADING_SPEED_THRESHOLD_PX_S) {
      this.headingDeg = Math.atan2(this.posY.velocity, this.posX.velocity) * DEG;
      this.rotation.target = this.headingDeg;
    } else if (this.move === null) {
      this.rotation.target = REST_ROTATION_DEG;
    }
    this.rotation.update(dt);
    this.visibility.update(dt);

    if (this.wobbleTime < WOBBLE_DURATION_S) this.wobbleTime += dt;
    const wobblePhase = clamp(this.wobbleTime / WOBBLE_DURATION_S, 0, 1);
    const wobble =
      wobblePhase < 1
        ? Math.sin(wobblePhase * Math.PI * 2 * 2) * WOBBLE_AMPLITUDE_DEG * (1 - wobblePhase)
        : 0;

    let x = this.posX.value;
    let y = this.posY.value;
    let rotation = this.rotation.value + wobble;
    if (move !== null && move.kind === 'scoot') {
      const total = distance(move.from, move.to);
      const covered = total < 1e-9 ? 1 : clamp(1 - distance(this.position, move.to) / total, 0, 1);
      const arc = Math.sin(Math.PI * covered);
      y += arc * SCOOT_DIP_PX;
      rotation += arc * SCOOT_TILT_DEG;
    }

    const opacity = clamp(this.visibility.value, 0, 1);
    return {
      x,
      y,
      rotationDeg: rotation,
      stretch: clamp(1 - speed / STRETCH_SPEED_DIVISOR, STRETCH_MIN, 1),
      headingDeg: this.headingDeg,
      opacity,
      visible: opacity > 0.01,
    };
  }

  private checkArrival(move: ActiveMove): void {
    const progress = move.kind === 'scoot' ? 1 : this.progress.value;
    const offset = distance(this.position, move.to);
    const speed = Math.hypot(this.posX.velocity, this.posY.velocity);
    if (progress >= ARRIVAL_PROGRESS && offset <= ARRIVAL_DISTANCE_PX && speed <= ARRIVAL_SPEED_PX_S) {
      this.move = null;
      this.posX.snap(move.to.x);
      this.posY.snap(move.to.y);
      this.rotation.target = REST_ROTATION_DEG;
      this.arrivedPending = true;
      this.wobbleTime = 0;
    }
  }
}
