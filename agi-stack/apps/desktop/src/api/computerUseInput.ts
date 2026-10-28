export type ComputerUseInputMode = 'background' | 'foreground';
export type ComputerUseInputPhase =
  | 'idle'
  | 'moving'
  | 'holding'
  | 'released'
  | 'paused'
  | 'stopped'
  | 'error';

export interface ComputerUseInputScope {
  readonly mode: 'local' | 'cloud';
  readonly tenant_id: string;
  readonly project_id: string;
}

/** Native receipts contain input state only, never typed text or key characters. */
export interface ComputerUseInput extends ComputerUseInputScope {
  readonly conversation_id: string;
  readonly run_id: string;
  readonly session_id: string;
  readonly input_mode: ComputerUseInputMode;
  readonly input_generation: string;
  readonly sequence: number;
  readonly updated_at: number;
  readonly phase: ComputerUseInputPhase;
  readonly target_pid: number;
  readonly target_window_id?: string;
  readonly virtual_cursor?: {
    readonly x: number;
    readonly y: number;
    readonly width: number;
    readonly height: number;
    readonly window_id: string;
  };
  readonly held_keys: readonly number[];
  readonly held_buttons: readonly number[];
  readonly evidence: 'dispatched' | 'observed';
  readonly reason?: string;
}

export type ComputerUseInputEvent =
  | Readonly<{ type: 'computer_use_input'; input: ComputerUseInput }>
  | Readonly<
      ComputerUseInputScope & {
        type: 'computer_use_input_reset';
        session_id?: string;
      }
    >;

const phases: readonly string[] = [
  'idle',
  'moving',
  'holding',
  'released',
  'paused',
  'stopped',
  'error',
];
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= 1024;
const integer = (value: unknown, maximum: number): value is number =>
  Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= maximum;
const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const codes = (value: unknown, maximum: number, count: number): value is number[] =>
  Array.isArray(value) && value.length <= count && value.every((code) => integer(code, maximum));

export function sameComputerUseInputScope(
  left: ComputerUseInputScope,
  right: ComputerUseInputScope,
): boolean {
  return (
    left.mode === right.mode &&
    left.tenant_id === right.tenant_id &&
    left.project_id === right.project_id
  );
}

function validScope(value: Record<string, unknown>): boolean {
  return (
    ['local', 'cloud'].includes(value.mode as string) &&
    identifier(value.tenant_id) &&
    identifier(value.project_id)
  );
}

/** Copy an allow-list so unrecognized payload content cannot enter UI state. */
export function parseComputerUseInput(value: unknown): ComputerUseInput | null {
  if (
    !record(value) ||
    !validScope(value) ||
    !['conversation_id', 'run_id', 'session_id', 'input_generation'].every((key) =>
      identifier(value[key]),
    ) ||
    !['background', 'foreground'].includes(value.input_mode as string) ||
    !phases.includes(value.phase as string) ||
    !integer(value.sequence, Number.MAX_SAFE_INTEGER) ||
    !finite(value.updated_at) ||
    !integer(value.target_pid, Number.MAX_SAFE_INTEGER) ||
    !codes(value.held_keys, 65535, 256) ||
    !codes(value.held_buttons, 31, 32) ||
    !['dispatched', 'observed'].includes(value.evidence as string) ||
    (value.target_window_id != null && !identifier(value.target_window_id)) ||
    (value.reason != null && !identifier(value.reason))
  )
    return null;
  let cursor: ComputerUseInput['virtual_cursor'];
  if (value.virtual_cursor != null) {
    const point = value.virtual_cursor;
    if (
      !record(point) ||
      !identifier(point.window_id) ||
      !finite(point.x) ||
      !finite(point.y) ||
      !finite(point.width) ||
      point.width <= 0 ||
      !finite(point.height) ||
      point.height <= 0 ||
      point.window_id !== value.target_window_id
    )
      return null;
    cursor = {
      x: point.x,
      y: point.y,
      width: point.width,
      height: point.height,
      window_id: point.window_id,
    };
  }
  return {
    mode: value.mode as ComputerUseInputScope['mode'],
    tenant_id: value.tenant_id as string,
    project_id: value.project_id as string,
    conversation_id: value.conversation_id as string,
    run_id: value.run_id as string,
    session_id: value.session_id as string,
    input_mode: value.input_mode as ComputerUseInputMode,
    input_generation: value.input_generation as string,
    sequence: value.sequence,
    updated_at: value.updated_at,
    phase: value.phase as ComputerUseInputPhase,
    target_pid: value.target_pid,
    ...(value.target_window_id == null
      ? {}
      : { target_window_id: value.target_window_id as string }),
    ...(cursor ? { virtual_cursor: cursor } : {}),
    held_keys: [...new Set(value.held_keys)],
    held_buttons: [...new Set(value.held_buttons)],
    evidence: value.evidence as ComputerUseInput['evidence'],
    ...(value.reason == null ? {} : { reason: value.reason as string }),
  };
}

export function parseComputerUseInputEvent(value: unknown): ComputerUseInputEvent | null {
  if (!record(value)) return null;
  if (value.type === 'computer_use_input') {
    const input = parseComputerUseInput(value.input);
    return input ? { type: 'computer_use_input', input } : null;
  }
  if (
    value.type !== 'computer_use_input_reset' ||
    !validScope(value) ||
    (value.session_id !== undefined && !identifier(value.session_id))
  )
    return null;
  return {
    type: 'computer_use_input_reset',
    mode: value.mode as ComputerUseInputScope['mode'],
    tenant_id: value.tenant_id as string,
    project_id: value.project_id as string,
    ...(value.session_id === undefined ? {} : { session_id: value.session_id as string }),
  };
}

export function computerUseInputIsVisible(input: ComputerUseInput): boolean {
  return !['paused', 'stopped', 'error'].includes(input.phase);
}
