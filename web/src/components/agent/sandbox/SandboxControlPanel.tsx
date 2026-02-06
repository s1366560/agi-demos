/**
 * SandboxControlPanel - Control panel for sandbox desktop and terminal services
 *
 * Provides status display and control buttons for desktop and terminal services.
 */

import { useCallback } from 'react';

import {
  DesktopOutlined,
  CodeOutlined,
  PlayCircleOutlined,
  StopOutlined,
  LinkOutlined,
} from '@ant-design/icons';
import { Card, Space, Button, Badge, Typography, Divider, Tooltip } from 'antd';

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
  onDesktopStart?: () => void;
  /** Called when stop desktop is requested */
  onDesktopStop?: () => void;
  /** Called when start terminal is requested */
  onTerminalStart?: () => void;
  /** Called when stop terminal is requested */
  onTerminalStop?: () => void;
  /** Loading state for desktop operations */
  isDesktopLoading?: boolean;
  /** Loading state for terminal operations */
  isTerminalLoading?: boolean;
}

interface ServiceStatusProps {
  type: 'desktop' | 'terminal';
  status: DesktopStatus | TerminalStatus | null;
  isLoading: boolean;
  onStart: () => void;
  onStop: () => void;
}

function ServiceStatusCard({ type, status, isLoading, onStart, onStop }: ServiceStatusProps) {
  const isRunning = status?.running ?? false;
  const icon = type === 'desktop' ? <DesktopOutlined /> : <CodeOutlined />;
  const name = type === 'desktop' ? 'Remote Desktop' : 'Web Terminal';

  return (
    <Card
      size="small"
      className={
        type === 'desktop' ? 'bg-blue-50 dark:bg-blue-950' : 'bg-green-50 dark:bg-green-950'
      }
    >
      <Space direction="vertical" className="w-full" style={{ width: '100%' }}>
        {/* Header */}
        <div className="flex items-center justify-between">
          <Space>
            {icon}
            <Text strong>{name}</Text>
          </Space>
          {isLoading ? (
            <Badge status="processing" text="Starting..." />
          ) : isRunning ? (
            <Badge status="success" text="Running" />
          ) : (
            <Badge status="default" text="Stopped" />
          )}
        </div>

        {/* Details */}
        {isRunning && status && (
          <>
            <Divider className="my-2" />
            <div className="space-y-1">
              {status.url && (
                <div className="flex items-center gap-2">
                  <LinkOutlined className="text-gray-500 text-xs" />
                  <Text copyable={{ text: status.url }} className="text-xs text-gray-600">
                    {status.url.length > 50 ? `${status.url.slice(0, 47)}...` : status.url}
                  </Text>
                </div>
              )}
              {type === 'desktop' && 'resolution' in status && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">Resolution:</span>
                  <span className="text-gray-700">{status.resolution}</span>
                </div>
              )}
              {'display' in status && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">Display:</span>
                  <span className="text-gray-700">{status.display}</span>
                </div>
              )}
              {'port' in status && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">Port:</span>
                  <span className="text-gray-700">{status.port}</span>
                </div>
              )}
              {'sessionId' in status && status.sessionId && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">Session:</span>
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
            <Tooltip title={`Stop ${name.toLowerCase()}`}>
              <Button
                type="primary"
                danger
                size="small"
                icon={<StopOutlined />}
                onClick={onStop}
                disabled={isLoading}
              >
                Stop
              </Button>
            </Tooltip>
          ) : (
            <Tooltip title={`Start ${name.toLowerCase()}`}>
              <Button
                type="primary"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={onStart}
                loading={isLoading}
              >
                Start
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
    <Space direction="vertical" size="middle" className="w-full">
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
