import { useEffect, useRef, useState } from 'react';

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
): TerminalProxyState {
  const socketRef = useRef<WebSocket | null>(null);
  const generationRef = useRef(0);
  const [status, setStatus] = useState<TerminalConnectionStatus>('idle');
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

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

    setStatus('connecting');
    const socket = openTerminalSocket(url, credential, launchCapability);
    socketRef.current = socket;
    let failed = false;
    const isCurrent = () => generationRef.current === generation && socketRef.current === socket;

    socket.onopen = () => {
      if (!isCurrent()) return;
      setStatus('connected');
      setError(null);
      socket.send(JSON.stringify({ type: 'resize', cols: 120, rows: 32 }));
    };
    socket.onerror = () => {
      if (!isCurrent()) return;
      failed = true;
      setStatus('error');
      setError('terminal_websocket_error');
    };
    socket.onclose = () => {
      if (!isCurrent()) return;
      socketRef.current = null;
      if (!failed) setStatus('closed');
    };
    socket.onmessage = (message) => {
      if (!isCurrent()) return;
      const frame = terminalFrame(message.data);
      setLines((current) => [...current, frame.line].slice(-300));
      if (frame.error) {
        failed = true;
        setStatus('error');
        setError(frame.error);
        socket.close();
      }
    };

    return () => {
      if (generationRef.current === generation) generationRef.current += 1;
      if (socketRef.current === socket) socketRef.current = null;
      socket.close();
    };
  }, [credential, launchCapability, url]);

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
      setLines([]);
    },
  };
}

export function openTerminalSocket(
  url: string,
  credential: string,
  launchCapability: string,
  Socket: typeof WebSocket = WebSocket,
): WebSocket {
  return new Socket(
    url,
    launchCapability
      ? ['memstack.launch', launchCapability, 'memstack.auth', credential]
      : ['memstack.auth', credential],
  );
}

export function terminalFrame(data: unknown): { line: string; error: string | null } {
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
    if (record.type === 'authority_revoked') {
      return {
        line: `[authority revoked] ${String(record.message ?? '')}`,
        error: String(record.code ?? 'terminal_authority_revoked'),
      };
    }
    if (record.type === 'error') {
      return {
        line: `[error] ${String(record.message ?? 'terminal failed')}`,
        error: 'terminal_remote_error',
      };
    }
    return { line: JSON.stringify(parsed), error: null };
  } catch {
    return { line: data, error: null };
  }
}
