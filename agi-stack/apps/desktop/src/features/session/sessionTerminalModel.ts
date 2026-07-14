import type {
  DesktopRun,
  TerminalConnectionStatus,
  TerminalServiceResponse,
} from '../../types';

export type TerminalBindingState = TerminalConnectionStatus | 'stale';

export function terminalSessionMatchesRun(
  terminal: TerminalServiceResponse | null,
  run: DesktopRun | null,
): boolean {
  if (!terminal?.success || !terminal.session_id || !run) return false;
  return (
    terminal.project_id === run.project_id &&
    terminal.conversation_id === run.conversation_id &&
    terminal.run_id === run.id &&
    terminal.run_revision === run.revision &&
    terminal.environment_id === run.environment?.id
  );
}

export function terminalBindingState(
  terminal: TerminalServiceResponse | null,
  run: DesktopRun | null,
  connectionStatus: TerminalConnectionStatus,
): TerminalBindingState {
  if (!terminal) return 'idle';
  if (!terminalSessionMatchesRun(terminal, run)) return 'stale';
  return connectionStatus;
}

export function terminalRunScopeKey(run: DesktopRun | null): string {
  if (!run) return '';
  return [run.project_id, run.conversation_id, run.id, run.revision, run.environment?.id ?? ''].join(
    ':',
  );
}

export function terminalOutputText(lines: string[], maxChunks?: number): string {
  const visibleLines = maxChunks ? lines.slice(-maxChunks) : lines;
  return visibleLines.join('');
}
