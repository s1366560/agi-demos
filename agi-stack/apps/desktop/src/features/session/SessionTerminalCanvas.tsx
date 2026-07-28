import { Badge, Button, Text } from '@radix-ui/themes';
import { DesktopIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { DesktopRun, TerminalServiceResponse } from '../../types';
import { InteractiveTerminal } from '../sandbox/InteractiveTerminal';
import { SessionSandboxTools } from '../sandbox/SessionSandboxTools';
import type { SandboxRuntimeCapability } from '../sandbox/sandboxRuntimeClient';
import type { SessionSandboxRuntimeSurface } from '../sandbox/useSandboxRuntimeSurface';
import { terminalOutputText, type TerminalBindingState } from './sessionTerminalModel';

type SessionTerminalCanvasProps = {
  terminal: TerminalServiceResponse | null;
  binding: TerminalBindingState;
  error: string | null;
  lines: string[];
  busy: boolean;
  currentRun: DesktopRun | null;
  onStart: () => void;
  interactiveCapability?: SandboxRuntimeCapability;
  sandboxRuntime?: SessionSandboxRuntimeSurface;
  onTerminalInput?: (data: string) => boolean | void;
  onTerminalResize?: (cols: number, rows: number) => void;
};

export function SessionTerminalCanvas({
  terminal,
  binding,
  error,
  lines,
  busy,
  currentRun,
  onStart,
  interactiveCapability = {
    availability: 'unavailable',
    contract_version: 1,
    reason_code: 'terminal_interactive_capability_unavailable',
  },
  sandboxRuntime,
  onTerminalInput,
  onTerminalResize,
}: SessionTerminalCanvasProps) {
  const { t } = useI18n();
  const canStart =
    !busy &&
    binding !== 'connecting' &&
    currentRun?.status === 'running' &&
    currentRun.permission_profile === 'full_access';
  const statusLabel =
    binding === 'connected'
      ? t('session.terminalConnected')
      : binding === 'connecting'
        ? t('session.terminalConnecting')
        : binding === 'closed'
          ? t('session.terminalClosed')
          : binding === 'stale'
            ? t('session.terminalStale')
            : binding === 'error'
              ? t('session.terminalError')
              : t('session.terminalIdle');
  const statusColor =
    binding === 'connected'
      ? 'green'
      : binding === 'error' || binding === 'stale'
        ? 'red'
        : binding === 'connecting'
          ? 'cyan'
          : 'gray';
  const interactive =
    interactiveCapability.availability === 'available' &&
    binding === 'connected' &&
    Boolean(onTerminalInput && onTerminalResize);
  return (
    <section className="review-terminal" aria-label={t('session.terminalTitle')}>
      <div className="review-section-title">
        <Text size="1" weight="bold" color="gray">
          {t('session.terminalTitle')}
        </Text>
        <Badge color={statusColor} variant="soft" role="status" aria-live="polite">
          {statusLabel}
        </Badge>
        <Button
          size="1"
          variant="surface"
          disabled={!canStart}
          title={
            currentRun?.permission_profile === 'full_access'
              ? undefined
              : t('session.terminalPermissionRequired')
          }
          onClick={onStart}
        >
          <DesktopIcon />
          {busy
            ? t('session.startingTerminal')
            : binding === 'closed' || binding === 'error' || binding === 'stale'
              ? t('session.openNewTerminal')
              : t('session.openRunTerminal')}
        </Button>
      </div>
      <Text size="1" color="gray">
        {terminal?.environment?.label ??
          currentRun?.environment?.label ??
          t('session.environmentUnavailable')}
        {terminal?.cwd
          ? ` · ${terminal.cwd}`
          : currentRun?.environment?.workspace_path
            ? ` · ${currentRun.environment.workspace_path}`
            : ''}
      </Text>
      {terminal ? (
        <Text size="1" color="gray">
          {t('session.terminalNonResumable')}
        </Text>
      ) : null}
      {currentRun?.permission_profile !== 'full_access' ? (
        <Text size="1" color="amber">
          {t('session.terminalPermissionRequired')}
        </Text>
      ) : null}
      {binding === 'stale' ? (
        <TerminalAlert title={t('session.terminalStale')} body={t('session.terminalStaleBody')} />
      ) : null}
      {binding === 'closed' ? (
        <TerminalAlert
          status
          title={t('session.terminalClosed')}
          body={t('session.terminalClosedBody')}
        />
      ) : null}
      {binding === 'error' ? (
        <TerminalAlert
          title={t('session.terminalError')}
          body={t('session.terminalErrorBody')}
          code={error}
        />
      ) : null}
      {interactive && onTerminalInput && onTerminalResize ? (
        <InteractiveTerminal
          ariaLabel={t('session.terminalOutput')}
          connected
          outputChunks={lines}
          onInput={(data) => {
            onTerminalInput(data);
          }}
          onResize={onTerminalResize}
        />
      ) : (
        <pre
          className="terminal-preview"
          role="log"
          tabIndex={0}
          aria-label={t('session.terminalOutput')}
        >
          {lines.length ? terminalOutputText(lines, 20) : t('session.terminalEmpty')}
        </pre>
      )}
      {sandboxRuntime ? <SessionSandboxTools runtime={sandboxRuntime} /> : null}
    </section>
  );
}

function TerminalAlert({
  title,
  body,
  code,
  status = false,
}: {
  title: string;
  body: string;
  code?: string | null;
  status?: boolean;
}) {
  return (
    <div className="terminal-authority-alert" role={status ? 'status' : 'alert'}>
      <strong>{title}</strong>
      <span>{body}</span>
      {code ? <code>{code}</code> : null}
    </div>
  );
}
