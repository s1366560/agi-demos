import { Badge, Button, Flex, Text, TextField } from '@radix-ui/themes';
import { DesktopIcon, LightningBoltIcon, ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  DesktopServiceResponse,
  ProjectSandbox,
  TerminalServiceResponse,
} from '../../types';
import {
  terminalOutputText,
  type TerminalBindingState,
} from '../session/sessionTerminalModel';

type SandboxPanelProps = {
  sandbox: ProjectSandbox | null;
  desktop: DesktopServiceResponse | null;
  desktopFrameUrl: string | null;
  terminal: TerminalServiceResponse | null;
  terminalBinding: TerminalBindingState;
  terminalError: string | null;
  terminalLines: string[];
  terminalInput: string;
  busy: boolean;
  disabledReason: string | null;
  onTerminalInputChange: (value: string) => void;
  onEnsureSandbox: () => void;
  onStartDesktop: () => void;
  onStartTerminal: () => void;
  onSendTerminalInput: () => void;
  onClearTerminal: () => void;
};

export function SandboxPanel({
  sandbox,
  desktop,
  desktopFrameUrl,
  terminal,
  terminalBinding,
  terminalError,
  terminalLines,
  terminalInput,
  busy,
  disabledReason,
  onTerminalInputChange,
  onEnsureSandbox,
  onStartDesktop,
  onStartTerminal,
  onSendTerminalInput,
  onClearTerminal,
}: SandboxPanelProps) {
  const { t } = useI18n();
  const disabled = Boolean(disabledReason);
  const terminalConnected = terminalBinding === 'connected';
  const desktopUnavailable = desktop?.success === false;
  const terminalUnavailable = terminal?.success === false;
  const desktopStatus = desktop
    ? desktop.success
      ? (desktop.resolution ?? t('sandbox.ready'))
      : t('sandbox.unavailable')
    : '—';
  const terminalStatus =
    terminalBinding === 'connected'
      ? t('session.terminalConnected')
      : terminalBinding === 'connecting'
        ? t('session.terminalConnecting')
        : terminalBinding === 'closed'
          ? t('session.terminalClosed')
          : terminalBinding === 'stale'
            ? t('session.terminalStale')
            : terminalBinding === 'error'
              ? t('session.terminalError')
              : terminalUnavailable
                ? t('sandbox.unavailable')
                : t('session.terminalIdle');
  const terminalStatusColor =
    terminalBinding === 'connected'
      ? 'green'
      : terminalBinding === 'connecting'
        ? 'cyan'
        : terminalBinding === 'stale' || terminalBinding === 'error'
          ? 'red'
          : 'gray';
  const terminalLogText = terminalLines.length
    ? terminalOutputText(terminalLines)
    : terminalUnavailable
      ? t('sandbox.terminalUnavailableDescription')
      : t('session.terminalEmpty');

  return (
    <section className="sandbox-panel">
      <Flex align="center" justify="between">
        <Text size="1" color="gray" weight="bold">
          {t('sandbox.title')}
        </Text>
        <Badge
          color={sandbox?.is_healthy ? 'green' : sandbox ? 'amber' : 'gray'}
          variant="soft"
          role="status"
          aria-live="polite"
        >
          {sandbox?.status ?? t('status.notLoaded')}
        </Badge>
      </Flex>

      <div className="sandbox-actions">
        <Button
          size="2"
          variant="surface"
          aria-label={t('sandbox.ensureRuntime')}
          onClick={onEnsureSandbox}
          loading={busy}
          disabled={disabled}
        >
          <ReloadIcon /> {t('sandbox.ensure')}
        </Button>
        <Button
          size="2"
          aria-label={t('sandbox.startDesktop')}
          onClick={onStartDesktop}
          loading={busy}
          disabled={disabled}
        >
          <DesktopIcon /> {t('sandbox.desktop')}
        </Button>
        <Button
          size="2"
          variant="surface"
          aria-label={t('sandbox.startTerminal')}
          onClick={onStartTerminal}
          loading={busy}
          disabled={disabled}
        >
          <LightningBoltIcon /> {t('status.terminal')}
        </Button>
      </div>
      {disabledReason ? (
        <Text size="1" color="gray" className="action-hint">
          {disabledReason}
        </Text>
      ) : null}

      <div className="metric-grid">
        <Metric label={t('status.sandbox')} value={sandbox?.sandbox_id ?? '—'} />
        <Metric label={t('sandbox.desktop')} value={desktopStatus} />
        <Metric label={t('status.terminal')} value={terminalStatus} />
        <div className="metric" role="status" aria-live="polite">
          <Text size="1" color="gray">
            {t('sandbox.liveShell')}
          </Text>
          <Badge color={terminalStatusColor} variant="soft">
            {terminalStatus}
          </Badge>
        </div>
      </div>

      {desktopFrameUrl && desktop?.success ? (
        <iframe
          className="desktop-frame"
          title={t('sandbox.desktopFrameTitle')}
          src={desktopFrameUrl}
          allow="clipboard-read; clipboard-write"
        />
      ) : (
        <div className="desktop-placeholder">
          <Text size="2" color="gray">
            {desktopUnavailable
              ? t('sandbox.desktopUnavailableDescription')
              : t('sandbox.desktopEmptyDescription')}
          </Text>
        </div>
      )}

      <div className="terminal-console">
        <Flex align="center" justify="between" mb="2">
          <Text size="1" color="gray" weight="bold">
            {t('session.terminalTitle')}
          </Text>
          <Button
            size="2"
            variant="ghost"
            aria-label={t('sandbox.clearTerminalOutput')}
            onClick={onClearTerminal}
          >
            {t('sandbox.clear')}
          </Button>
        </Flex>
        {terminalBinding === 'error' ? (
          <div className="terminal-authority-alert" role="alert">
            <strong>{t('session.terminalError')}</strong>
            <span>{t('session.terminalErrorBody')}</span>
            {terminalError ? <code>{terminalError}</code> : null}
          </div>
        ) : null}
        {terminalBinding === 'stale' ? (
          <div className="terminal-authority-alert" role="alert">
            <strong>{t('session.terminalStale')}</strong>
            <span>{t('session.terminalStaleBody')}</span>
          </div>
        ) : null}
        <pre
          className="terminal-log"
          role="log"
          tabIndex={0}
          aria-label={t('session.terminalOutput')}
        >
          {terminalLogText}
        </pre>
        <label className="terminal-input-label" htmlFor="sandbox-terminal-input">
          {t('sandbox.terminalInput')}
        </label>
        <Flex gap="2" mt="2">
          <TextField.Root
            id="sandbox-terminal-input"
            aria-label={t('sandbox.terminalInput')}
            value={terminalInput}
            disabled={disabled || !terminalConnected}
            onChange={(event) => onTerminalInputChange(event.target.value)}
            placeholder="ls -la"
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                onSendTerminalInput();
              }
            }}
          />
          <Button
            size="2"
            aria-label={t('sandbox.sendTerminalInput')}
            onClick={onSendTerminalInput}
            disabled={disabled || !terminalConnected}
          >
            {t('sandbox.send')}
          </Button>
        </Flex>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <Text size="1" color="gray">
        {label}
      </Text>
      <Text size="2" weight="bold">
        {value}
      </Text>
    </div>
  );
}
