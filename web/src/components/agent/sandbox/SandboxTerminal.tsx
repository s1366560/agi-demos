/**
 * SandboxTerminal - Interactive terminal component using xterm.js
 *
 * Connects to backend terminal WebSocket and provides full terminal emulation
 * for interacting with sandbox containers.
 *
 * xterm.js dependencies are dynamically imported within the component
 * to reduce initial bundle size.
 */

import {
  lazy,
  Suspense,
  useState,
  useCallback,
  useSyncExternalStore,
  useLayoutEffect,
  useRef,
} from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Button } from 'antd';
import { RefreshCw, Maximize2, Minimize2 } from 'lucide-react';

import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
} from '@/plugins/webOperationAdmissionV2';

import { Spinner } from '@/components/common/Spinner';

import { terminalScopeKeyV2 } from './terminalScopeV2';

// Lazy load terminal dependencies
import '@xterm/xterm/css/xterm.css';

export interface SandboxTerminalProps {
  /** Sandbox container ID */
  sandboxId: string;
  /** Project ID for project-scoped WebSocket */
  projectId?: string | undefined;
  /** Optional existing session ID to reconnect */
  sessionId?: string | undefined;
  /** Explicit manual new-terminal request; automatic retries keep their current session. */
  reconnectNonce?: number | undefined;
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

export function SandboxTerminal(props: SandboxTerminalProps) {
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );
  const scopeKey = terminalScopeKeyV2(availability.owner, props.projectId, props.sandboxId);
  const [binding, setBinding] = useState({ scopeKey, sessionId: props.sessionId });
  if (binding.scopeKey !== scopeKey) setBinding({ scopeKey, sessionId: undefined });
  if (!availability.available) return null;
  return (
    <TerminalSession
      key={JSON.stringify([scopeKey, props.reconnectNonce ?? 0])}
      {...props}
      sessionId={
        scopeKey === binding.scopeKey && !props.reconnectNonce ? binding.sessionId : undefined
      }
      owner={availability.owner}
    />
  );
}

function TerminalSession({
  sandboxId,
  projectId,
  sessionId: initialSessionId,
  onConnect,
  onDisconnect,
  onError,
  height = '100%',
  showToolbar = true,
  owner,
}: SandboxTerminalProps & { owner: object }) {
  const { t } = useTranslation();
  const active = useRef(false);
  const attempt = useRef(0);
  const [reconnectNonce, setReconnectNonce] = useState(0);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const current = useCallback(
    () =>
      active.current &&
      attempt.current === reconnectNonce &&
      getWebOperationAvailabilityV2().available &&
      getWebOperationAvailabilityV2().owner === owner,
    [owner, reconnectNonce]
  );
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId || null);
  const [error, setError] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const handleConnect = useCallback(
    (newSessionId: string) => {
      if (!current()) return;
      setSessionId(newSessionId);
      setStatus('connected');
      onConnect?.(newSessionId);
    },
    [onConnect, current]
  );

  const handleDisconnect = useCallback(() => {
    if (!current()) return;
    setStatus('disconnected');
    onDisconnect?.();
  }, [onDisconnect, current]);

  const handleError = useCallback(
    (errorMsg: string) => {
      if (!current()) return;
      setError(errorMsg);
      setStatus('error');
      onError?.(errorMsg);
    },
    [onError, current]
  );

  const reconnect = useCallback(() => {
    setSessionId(null);
    setStatus('connecting');
    setError(null);
    // Remount TerminalImpl so the existing socket is closed and a fresh one is opened
    attempt.current++;
    setReconnectNonce(attempt.current);
  }, []);

  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((prev) => !prev);
  }, []);

  return (
    <div
      className={`flex flex-col ${isFullscreen ? 'fixed inset-0 z-50 bg-background-dark' : ''}`}
      style={{ height: isFullscreen ? '100vh' : height }}
    >
      {/* Toolbar */}
      {showToolbar && (
        <div className="flex items-center justify-between px-3 py-2 bg-surface-dark border-b border-border-dark">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                status === 'connected'
                  ? 'bg-green-500'
                  : status === 'connecting'
                    ? 'bg-yellow-500 animate-pulse motion-reduce:animate-none'
                    : status === 'error'
                      ? 'bg-red-500'
                      : 'bg-gray-500'
              }`}
            />
            <span className="text-xs text-gray-400">
              {status === 'connected'
                ? t('components.sandboxTerminal.connected', {
                    defaultValue: 'Terminal ({{sessionId}})',
                    sessionId:
                      sessionId?.slice(0, 8) ??
                      t('components.sandboxTerminal.unknown', { defaultValue: 'unknown' }),
                  })
                : status === 'connecting'
                  ? t('components.sandboxTerminal.connecting', { defaultValue: 'Connecting…' })
                  : status === 'error'
                    ? t('components.sandboxTerminal.error', { defaultValue: 'Error' })
                    : t('components.sandboxTerminal.disconnected', {
                        defaultValue: 'Disconnected',
                      })}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              type="text"
              size="small"
              icon={<RefreshCw size={16} />}
              onClick={reconnect}
              className="text-gray-400 hover:text-white"
              title={t('components.sandboxTerminal.reconnect', { defaultValue: 'Reconnect' })}
              aria-label={t('components.sandboxTerminal.reconnect', {
                defaultValue: 'Reconnect',
              })}
            />
            <Button
              type="text"
              size="small"
              icon={isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
              onClick={toggleFullscreen}
              className="text-gray-400 hover:text-white"
              title={
                isFullscreen
                  ? t('components.sandboxTerminal.exitFullscreen', {
                      defaultValue: 'Exit Fullscreen',
                    })
                  : t('components.sandboxTerminal.fullscreen', { defaultValue: 'Fullscreen' })
              }
              aria-label={
                isFullscreen
                  ? t('components.sandboxTerminal.exitFullscreen', {
                      defaultValue: 'Exit Fullscreen',
                    })
                  : t('components.sandboxTerminal.fullscreen', { defaultValue: 'Fullscreen' })
              }
            />
          </div>
        </div>
      )}

      {/* Terminal */}
      <div className="flex-1 relative">
        {status === 'connecting' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background-dark z-10">
            <Spinner />
            <span className="text-slate-400">
              {t('components.sandboxTerminal.connectingToTerminal', {
                defaultValue: 'Connecting to terminal…',
              })}
            </span>
          </div>
        )}

        {error && status === 'error' && (
          <Alert
            type="error"
            title={t('components.sandboxTerminal.connectionError', {
              defaultValue: 'Connection Error',
            })}
            description={error}
            showIcon
            className="m-4"
            action={
              <Button size="small" onClick={reconnect}>
                {t('components.sandboxTerminal.retry', { defaultValue: 'Retry' })}
              </Button>
            }
          />
        )}

        <Suspense
          fallback={
            <div className="h-full w-full flex items-center justify-center bg-background-dark text-slate-400">
              <Spinner />{' '}
              {t('components.sandboxTerminal.loadingTerminal', {
                defaultValue: 'Loading terminal…',
              })}
            </div>
          }
        >
          <TerminalImpl
            key={reconnectNonce}
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
