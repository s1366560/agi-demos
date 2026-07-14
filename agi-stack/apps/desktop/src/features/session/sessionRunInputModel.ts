import type { DesktopRunInput } from '../../types';

export type QueuedRunInputHandoffState = 'waiting' | 'ready' | 'blocked' | 'promoted';

export function queuedRunInputHandoffState(
  input: DesktopRunInput,
): QueuedRunInputHandoffState | null {
  if (input.delivery !== 'queue_next') return null;
  switch (input.status) {
    case 'queued':
      return 'waiting';
    case 'ready':
      return 'ready';
    case 'blocked':
      return 'blocked';
    case 'promoted_to_plan':
      return 'promoted';
    default:
      return null;
  }
}

export function visibleQueuedRunInputs(inputs: DesktopRunInput[]): DesktopRunInput[] {
  return inputs.filter((input) => queuedRunInputHandoffState(input) !== null);
}
