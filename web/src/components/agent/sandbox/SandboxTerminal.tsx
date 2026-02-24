/**
 * SandboxTerminal - Interactive terminal component using xterm.js
 *
 * Connects to backend terminal WebSocket and provides full terminal emulation
 * for interacting with sandbox containers.
 *
 * xterm.js dependencies are dynamically imported within the component
 * to reduce initial bundle size.
 */

import { lazy, Suspense, useState, useCallback } from 'react';

import { ReloadOutlined, ExpandOutlined, CompressOutlined } from '@ant-design/icons';
import { Spin, Alert, Button } from 'antd';

// Lazy load terminal dependencies
import '@xterm/xterm/css/xterm.css';

export interface SandboxTerminalProps {
  /** Sandbox container ID */
  sandboxId: string;
  /** Project ID for project-scoped WebSocket */
  projectId?: string | undefined;
  /** Optional existing session ID to reconnect */
  sessionId?: string | undefined;
  /** Called when terminal connects */
  onConnect?: ((sessionId: string) => void) | undefined;
  /** Called when terminal disconnects */
  onDisconnect?: (() => void) | undefined;
  /** Called on terminal error */
  onError?: ((error: string) => void) | undefined;
  /** Terminal height (default: 100%) */
  height?: string | number | undefined;
  /** Show toolbar (default: true) */
  showToolbar?: boolean | undefined;
}

type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

// Lazy loaded terminal implementation
const TerminalImpl = lazy(() => import('./TerminalImpl'));

export function SandboxTerminal({
  sandboxId,
  projectId,
  sessionId: initialSessionId,
  onConnect,
  onDisconnect,
  onError,
  height = '100%',
  showToolbar = true,
}: SandboxTerminalProps) {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId || null);
  const [error, setError] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const handleConnect = useCallback(
    (newSessionId: string) => {
      setSessionId(newSessionId);
      setStatus('connected');
      onConnect?.(newSessionId);
    },
    [onConnect]
  );

  const handleDisconnect = useCallback(() => {
    setStatus('disconnected');
    onDisconnect?.();
  }, [onDisconnect]);

  const handleError = useCallback(
    (errorMsg: string) => {
      setError(errorMsg);
      setStatus('error');
      onError?.(errorMsg);
    },
    [onError]
  );

  const reconnect = useCallback(() => {
    setSessionId(null);
    setStatus('disconnected');
    setError(null);
  }, []);

  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((prev) => !prev);
  }, []);

  return (
    <div
      className={`flex flex-col ${isFullscreen ? 'fixed inset-0 z-50 bg-[#1e1e1e]' : ''}`}
      style={{ height: isFullscreen ? '100vh' : height }}
    >
      {/* Toolbar */}
      {showToolbar && (
        <div className="flex items-center justify-between px-3 py-2 bg-[#252526] border-b border-[#3c3c3c]">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                status === 'connected'
                  ? 'bg-green-500'
                  : status === 'connecting'
                    ? 'bg-yellow-500 animate-pulse'
                    : status === 'error'
                      ? 'bg-red-500'
                      : 'bg-gray-500'
              }`}
            />
            <span className="text-xs text-gray-400">
              {status === 'connected'
                ? `Terminal (${sessionId?.slice(0, 8)})`
                : status === 'connecting'
                  ? 'Connecting...'
                  : status === 'error'
                    ? 'Error'
                    : 'Disconnected'}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined />}
              onClick={reconnect}
              className="text-gray-400 hover:text-white"
              title="Reconnect"
            />
            <Button
              type="text"
              size="small"
              icon={isFullscreen ? <CompressOutlined /> : <ExpandOutlined />}
              onClick={toggleFullscreen}
              className="text-gray-400 hover:text-white"
              title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
            />
          </div>
        </div>
      )}

      {/* Terminal */}
      <div className="flex-1 relative">
        {status === 'connecting' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[#1e1e1e] z-10">
            <Spin />
            <span className="text-slate-400">Connecting to terminal...</span>
          </div>
        )}

        {error && status === 'error' && (
          <Alert
            type="error"
            message="Connection Error"
            description={error}
            showIcon
            className="m-4"
            action={
              <Button size="small" onClick={reconnect}>
                Retry
              </Button>
            }
          />
        )}

        <Suspense
          fallback={
            <div className="h-full w-full flex items-center justify-center bg-[#1e1e1e] text-slate-400">
              <Spin /> Loading terminal...
            </div>
          }
        >
          <TerminalImpl
            sandboxId={sandboxId}
            projectId={projectId}
            sessionId={sessionId || undefined}
            onConnect={handleConnect}
            onDisconnect={handleDisconnect}
            onError={handleError}
            status={status}
            isFullscreen={isFullscreen}
          />
        </Suspense>
      </div>
    </div>
  );
}

export default SandboxTerminal;
