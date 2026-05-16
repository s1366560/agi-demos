/**
 * SandboxControlPanel - Control panel for sandbox desktop and terminal services
 *
 * Provides status display and control buttons for desktop and terminal services.
 */

import { useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Card, Space, Button, Badge, Typography, Divider, Tooltip } from 'antd';
import { Monitor, Code, PlayCircle, Square, Link } from 'lucide-react';

import type { DesktopStatus, TerminalStatus } from '../../../types/agent';

const { Text } = Typography;

export interface SandboxControlPanelProps {
  /** Sandbox container ID */
  sandboxId: string;
  /** Desktop status information */
  desktopStatus: DesktopStatus | null;
  /** Terminal status information */
  terminalStatus: TerminalStatus | null;
  /** Called when start desktop is requested */
  onDesktopStart?: (() => void) | undefined;
  /** Called when stop desktop is requested */
  onDesktopStop?: (() => void) | undefined;
  /** Called when start terminal is requested */
  onTerminalStart?: (() => void) | undefined;
  /** Called when stop terminal is requested */
  onTerminalStop?: (() => void) | undefined;
  /** Loading state for desktop operations */
  isDesktopLoading?: boolean | undefined;
  /** Loading state for terminal operations */
  isTerminalLoading?: boolean | undefined;
}

interface ServiceStatusProps {
  type: 'desktop' | 'terminal';
  status: DesktopStatus | TerminalStatus | null;
  isLoading: boolean;
  onStart: () => void;
  onStop: () => void;
}

function ServiceStatusCard({ type, status, isLoading, onStart, onStop }: ServiceStatusProps) {
  const { t } = useTranslation();
  const isRunning = status?.running ?? false;
  const icon = type === 'desktop' ? <Monitor size={16} /> : <Code size={16} />;
  const name =
    type === 'desktop'
      ? t('components.sandboxControl.remoteDesktop', { defaultValue: 'Remote Desktop' })
      : t('components.sandboxControl.webTerminal', { defaultValue: 'Web Terminal' });

  return (
    <Card
      size="small"
      className={
        type === 'desktop' ? 'bg-blue-50 dark:bg-blue-950' : 'bg-green-50 dark:bg-green-950'
      }
    >
      <Space orientation="vertical" className="w-full" style={{ width: '100%' }}>
        {/* Header */}
        <div className="flex items-center justify-between">
          <Space>
            {icon}
            <Text strong>{name}</Text>
          </Space>
          {isLoading ? (
            <Badge
              status="processing"
              text={t('components.sandboxControl.starting', { defaultValue: 'Starting...' })}
            />
          ) : isRunning ? (
            <Badge
              status="success"
              text={t('components.sandboxControl.running', { defaultValue: 'Running' })}
            />
          ) : (
            <Badge
              status="default"
              text={t('components.sandboxControl.stopped', { defaultValue: 'Stopped' })}
            />
          )}
        </div>

        {/* Details */}
        {isRunning && status && (
          <>
            <Divider className="my-2" />
            <div className="space-y-1">
              {status.url && (
                <div className="flex items-center gap-2">
                  <Link size={12} className="text-gray-500" />
                  <Text copyable={{ text: status.url }} className="text-xs text-gray-600">
                    {status.url.length > 50 ? `${status.url.slice(0, 47)}...` : status.url}
                  </Text>
                </div>
              )}
              {type === 'desktop' && 'resolution' in status && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">
                    {t('components.sandboxControl.resolution', { defaultValue: 'Resolution:' })}
                  </span>
                  <span className="text-gray-700">{status.resolution}</span>
                </div>
              )}
              {'display' in status && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">
                    {t('components.sandboxControl.display', { defaultValue: 'Display:' })}
                  </span>
                  <span className="text-gray-700">{status.display}</span>
                </div>
              )}
              {'port' in status && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">
                    {t('components.sandboxControl.port', { defaultValue: 'Port:' })}
                  </span>
                  <span className="text-gray-700">{status.port}</span>
                </div>
              )}
              {'sessionId' in status && status.sessionId && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">
                    {t('components.sandboxControl.session', { defaultValue: 'Session:' })}
                  </span>
                  <span className="text-gray-700">{status.sessionId.slice(0, 8)}...</span>
                </div>
              )}
            </div>
          </>
        )}

        {/* Actions */}
        <Divider className="my-2" />
        <div className="flex justify-end">
          {isRunning ? (
            <Tooltip
              title={t('components.sandboxControl.stopService', {
                defaultValue: 'Stop {{name}}',
                name: name.toLowerCase(),
              })}
            >
              <Button
                type="primary"
                danger
                size="small"
                icon={<Square size={16} />}
                onClick={onStop}
                disabled={isLoading}
              >
                {t('components.sandboxControl.stop', { defaultValue: 'Stop' })}
              </Button>
            </Tooltip>
          ) : (
            <Tooltip
              title={t('components.sandboxControl.startService', {
                defaultValue: 'Start {{name}}',
                name: name.toLowerCase(),
              })}
            >
              <Button
                type="primary"
                size="small"
                icon={<PlayCircle size={16} />}
                onClick={onStart}
                loading={isLoading}
              >
                {t('components.sandboxControl.start', { defaultValue: 'Start' })}
              </Button>
            </Tooltip>
          )}
        </div>
      </Space>
    </Card>
  );
}

export function SandboxControlPanel({
  desktopStatus,
  terminalStatus,
  onDesktopStart,
  onDesktopStop,
  onTerminalStart,
  onTerminalStop,
  isDesktopLoading = false,
  isTerminalLoading = false,
}: SandboxControlPanelProps) {
  const handleDesktopStart = useCallback(() => {
    onDesktopStart?.();
  }, [onDesktopStart]);

  const handleDesktopStop = useCallback(() => {
    onDesktopStop?.();
  }, [onDesktopStop]);

  const handleTerminalStart = useCallback(() => {
    onTerminalStart?.();
  }, [onTerminalStart]);

  const handleTerminalStop = useCallback(() => {
    onTerminalStop?.();
  }, [onTerminalStop]);

  return (
    <Space orientation="vertical" size="middle" className="w-full">
      {/* Desktop Status Card */}
      <ServiceStatusCard
        type="desktop"
        status={desktopStatus}
        isLoading={isDesktopLoading}
        onStart={handleDesktopStart}
        onStop={handleDesktopStop}
      />

      {/* Terminal Status Card */}
      <ServiceStatusCard
        type="terminal"
        status={terminalStatus}
        isLoading={isTerminalLoading}
        onStart={handleTerminalStart}
        onStop={handleTerminalStop}
      />
    </Space>
  );
}

export default SandboxControlPanel;
