import { useCallback, useEffect, useRef, useState } from 'react';

import {
  terminalReconnectDecision,
  type TerminalDisconnectEvent,
  type TerminalSessionV2,
} from '../features/sandbox/terminalSessionV2';
import type { TerminalConnectionStatus } from '../types';

type TerminalProxyState = {
  status: TerminalConnectionStatus;
  connected: boolean;
  lines: string[];
  error: string | null;
  sendInput: (data: string) => boolean;
  resize: (cols: number, rows: number) => void;
  close: () => void;
  clear: () => void;
};

export function useTerminalProxy(
  url: string | null,
  credential: string,
  launchCapability: string,
  recovery?: {
    session: TerminalSessionV2 | null;
    onRefetchRun: (reasonCode: string) => void;
  },
): TerminalProxyState {
  const socketRef = useRef<WebSocket | null>(null);
  const generationRef = useRef(0);
  const pendingLinesRef = useRef<string[]>([]);
  const linesFlushCancelRef = useRef<(() => void) | null>(null);
  const [status, setStatus] = useState<TerminalConnectionStatus>('idle');
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const flushPendingLines = useCallback(() => {
    linesFlushCancelRef.current = null;
    const pending = pendingLinesRef.current;
    if (!pending.length) return;
    pendingLinesRef.current = [];
    setLines((current) => [...current, ...pending].slice(-300));
  }, []);

  const scheduleLinesFlush = useCallback(() => {
    if (linesFlushCancelRef.current) return;
    if (typeof requestAnimationFrame === 'function') {
      const frame = requestAnimationFrame(flushPendingLines);
      linesFlushCancelRef.current = () => cancelAnimationFrame(frame);
    } else {
      const timer = setTimeout(flushPendingLines, 16);
      linesFlushCancelRef.current = () => clearTimeout(timer);
    }
  }, [flushPendingLines]);

  useEffect(() => {
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    socketRef.current?.close();
    socketRef.current = null;
    setLines([]);
    setError(null);
    if (!url || !credential) {
      setStatus(url && !credential ? 'error' : 'idle');
      setError(url && !credential ? 'terminal_credential_unavailable' : null);
      return;
    }

    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempts = 0;
    let disconnectEvent: TerminalDisconnectEvent | null = null;
    const recoveryConfig = recovery;

    const connect = () => {
      if (disposed || generationRef.current !== generation) return;
      setStatus('connecting');
      const socket = openTerminalSocket(
        url,
        credential,
        launchCapability,
        WebSocket,
        recoveryConfig?.session?.resume_token ?? '',
      );
      socketRef.current = socket;
      const isCurrent = () =>
        !disposed && generationRef.current === generation && socketRef.current === socket;

      socket.onopen = () => {
        if (!isCurrent()) return;
        disconnectEvent = null;
        setStatus('connected');
        setError(null);
        socket.send(JSON.stringify({ type: 'resize', cols: 120, rows: 32 }));
      };
      socket.onerror = () => {
        if (!isCurrent()) return;
        setError('terminal_websocket_error');
      };
      socket.onclose = (event) => {
        if (!isCurrent()) return;
        socketRef.current = null;
        const session = recoveryConfig?.session ?? null;
        if (!session || !recoveryConfig) {
          setStatus(event.code === 1000 ? 'closed' : 'error');
          if (event.code !== 1000) setError('terminal_websocket_error');
          return;
        }
        const decision = terminalReconnectDecision(
          session,
          disconnectEvent ?? (event.code === 1000 ? { kind: 'normal_close' } : { kind: 'abnormal_close' }),
          reconnectAttempts,
        );
        if (decision.action === 'resume') {
          reconnectAttempts += 1;
          setStatus('connecting');
          setError(null);
          reconnectTimer = setTimeout(connect, decision.delay_ms);
          return;
        }
        setStatus(decision.action === 'refetch_run' ? 'error' : 'closed');
        setError(decision.reason_code);
        if (decision.action === 'refetch_run') {
          recoveryConfig.onRefetchRun(decision.reason_code);
        }
      };
      socket.onmessage = (message) => {
        if (!isCurrent()) return;
        const frame = terminalFrame(message.data);
        pendingLinesRef.current.push(frame.line);
        scheduleLinesFlush();
        if (frame.disconnect) disconnectEvent = frame.disconnect;
        if (frame.error) {
          setStatus('error');
          setError(frame.error);
          socket.close();
        }
      };
    };
    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (generationRef.current === generation) generationRef.current += 1;
      const socket = socketRef.current;
      socketRef.current = null;
      linesFlushCancelRef.current?.();
      linesFlushCancelRef.current = null;
      pendingLinesRef.current = [];
      socket?.close();
    };
  }, [credential, launchCapability, recovery, scheduleLinesFlush, url]);

  return {
    status,
    connected: status === 'connected',
    lines,
    error,
    sendInput(data: string) {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: 'input', data }));
        return true;
      }
      return false;
    },
    resize(cols: number, rows: number) {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: 'resize', cols, rows }));
      }
    },
    close() {
      generationRef.current += 1;
      socketRef.current?.close();
      socketRef.current = null;
      setStatus('closed');
    },
    clear() {
      linesFlushCancelRef.current?.();
      linesFlushCancelRef.current = null;
      pendingLinesRef.current = [];
      setLines([]);
    },
  };
}

export function openTerminalSocket(
  url: string,
  credential: string,
  launchCapability: string,
  Socket: typeof WebSocket = WebSocket,
  resumeToken = '',
): WebSocket {
  const protocols = launchCapability
    ? ['memstack.launch', launchCapability, 'memstack.auth', credential]
    : ['memstack.auth', credential];
  if (resumeToken) protocols.push('memstack.terminal-v2', resumeToken);
  return new Socket(url, protocols);
}

export function terminalFrame(data: unknown): {
  line: string;
  error: string | null;
  disconnect?: TerminalDisconnectEvent;
} {
  if (typeof data !== 'string') return { line: '[binary terminal frame]', error: null };
  try {
    const parsed = JSON.parse(data);
    if (!parsed || typeof parsed !== 'object') return { line: data, error: null };
    const record = parsed as Record<string, unknown>;
    if (record.type === 'output') return { line: String(record.data ?? ''), error: null };
    if (record.type === 'connected') {
      const sessionId = String(record.session_id ?? '');
      const cols = String(record.cols ?? '');
      const rows = String(record.rows ?? '');
      return { line: `[connected] session=${sessionId} ${cols}x${rows}`, error: null };
    }
    if (record.type === 'authority_revoked' || record.type === 'terminal_authority_revoked') {
      return {
        line: `[authority revoked] ${String(record.message ?? '')}`,
        error: String(record.code ?? 'terminal_authority_revoked'),
        disconnect: { kind: 'authority_revoked' },
      };
    }
    if (record.type === 'session_lost' || record.type === 'terminal_session_lost') {
      return {
        line: `[session lost] ${String(record.message ?? '')}`,
        error: 'terminal_session_lost',
        disconnect: { kind: 'session_lost' },
      };
    }
    if (record.type === 'error') {
      const code =
        record.code === 'terminal_session_lost'
          ? 'terminal_session_lost'
          : 'terminal_remote_error';
      return {
        line: `[error] ${String(record.message ?? 'terminal failed')}`,
        error: code,
      };
    }
    return { line: JSON.stringify(parsed), error: null };
  } catch {
    return { line: data, error: null };
  }
}
