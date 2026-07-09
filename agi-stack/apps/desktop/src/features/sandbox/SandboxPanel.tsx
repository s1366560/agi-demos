import { Badge, Button, Flex, Text, TextField } from '@radix-ui/themes';
import { DesktopIcon, LightningBoltIcon, ReloadIcon } from '@radix-ui/react-icons';

import type {
  DesktopServiceResponse,
  ProjectSandbox,
  TerminalServiceResponse,
} from '../../types';

type SandboxPanelProps = {
  sandbox: ProjectSandbox | null;
  desktop: DesktopServiceResponse | null;
  desktopFrameUrl: string | null;
  terminal: TerminalServiceResponse | null;
  terminalConnected: boolean;
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
  terminalConnected,
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
  const disabled = Boolean(disabledReason);
  const desktopUnavailable = desktop?.success === false;
  const terminalUnavailable = terminal?.success === false;
  const desktopStatus = desktop ? (desktop.success ? (desktop.resolution ?? 'ready') : 'unavailable') : '-';
  const terminalStatus = terminal
    ? terminal.success && terminal.session_id
      ? 'ready'
      : 'unavailable'
    : '-';
  const terminalLogText = terminalLines.length
    ? terminalLines.join('')
    : terminalUnavailable
      ? 'Terminal service responded without an attachable proxy. Start a production sandbox runtime to open an interactive shell.'
      : 'Terminal output appears here.';

  return (
    <section className="sandbox-panel">
      <Flex align="center" justify="between">
        <Text size="1" color="gray" weight="bold">
          SANDBOX
        </Text>
        <Badge color={sandbox?.is_healthy ? 'green' : sandbox ? 'amber' : 'gray'} variant="soft">
          {sandbox?.status ?? 'not loaded'}
        </Badge>
      </Flex>

      <div className="sandbox-actions">
        <Button
          size="2"
          variant="surface"
          aria-label="Ensure sandbox runtime"
          onClick={onEnsureSandbox}
          loading={busy}
          disabled={disabled}
        >
          <ReloadIcon /> Ensure
        </Button>
        <Button
          size="2"
          aria-label="Start sandbox desktop"
          onClick={onStartDesktop}
          loading={busy}
          disabled={disabled}
        >
          <DesktopIcon /> Desktop
        </Button>
        <Button
          size="2"
          variant="surface"
          aria-label="Start sandbox terminal"
          onClick={onStartTerminal}
          loading={busy}
          disabled={disabled}
        >
          <LightningBoltIcon /> Terminal
        </Button>
      </div>
      {disabledReason ? (
        <Text size="1" color="gray" className="action-hint">
          {disabledReason}
        </Text>
      ) : null}

      <div className="metric-grid">
        <Metric label="Sandbox" value={sandbox?.sandbox_id ?? '-'} />
        <Metric label="Desktop" value={desktopStatus} />
        <Metric label="Terminal" value={terminalStatus} />
        <Metric
          label="Live shell"
          value={terminalConnected ? 'connected' : terminalError ?? 'idle'}
        />
      </div>

      {desktopFrameUrl && desktop?.success ? (
        <iframe
          className="desktop-frame"
          title="Sandbox desktop"
          src={desktopFrameUrl}
          allow="clipboard-read; clipboard-write"
        />
      ) : (
        <div className="desktop-placeholder">
          <Text size="2" color="gray">
            {desktopUnavailable
              ? 'Desktop service responded without an attachable proxy. Start a production sandbox runtime to view the remote desktop here.'
              : 'Start the sandbox desktop to view the workspace environment here.'}
          </Text>
        </div>
      )}

      <div className="terminal-console">
        <Flex align="center" justify="between" mb="2">
          <Text size="1" color="gray" weight="bold">
            TERMINAL
          </Text>
          <Button
            size="2"
            variant="ghost"
            aria-label="Clear terminal output"
            onClick={onClearTerminal}
          >
            Clear
          </Button>
        </Flex>
        <pre className="terminal-log">{terminalLogText}</pre>
        <Flex gap="2" mt="2">
          <TextField.Root
            aria-label="Terminal input"
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
            aria-label="Send terminal input"
            onClick={onSendTerminalInput}
            disabled={disabled || !terminalConnected}
          >
            Send
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
