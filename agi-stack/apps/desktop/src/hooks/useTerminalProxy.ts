import { useEffect, useRef, useState } from 'react';

type TerminalProxyState = {
  connected: boolean;
  lines: string[];
  error: string | null;
  sendInput: (data: string) => void;
  resize: (cols: number, rows: number) => void;
  clear: () => void;
};

export function useTerminalProxy(url: string | null, credential: string): TerminalProxyState {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!url || !credential) {
      setConnected(false);
      setError(url && !credential ? 'Terminal credential is unavailable' : null);
      socketRef.current?.close();
      socketRef.current = null;
      return;
    }

    const socket = openTerminalSocket(url, credential);
    socketRef.current = socket;

    socket.onopen = () => {
      setConnected(true);
      setError(null);
      socket.send(JSON.stringify({ type: 'resize', cols: 120, rows: 32 }));
    };
    socket.onerror = () => setError('Terminal WebSocket error');
    socket.onclose = () => setConnected(false);
    socket.onmessage = (message) => {
      setLines((current) => [...current, terminalLine(message.data)].slice(-300));
    };

    return () => {
      socket.close();
    };
  }, [credential, url]);

  return {
    connected,
    lines,
    error,
    sendInput(data: string) {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: 'input', data }));
      }
    },
    resize(cols: number, rows: number) {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: 'resize', cols, rows }));
      }
    },
    clear() {
      setLines([]);
    },
  };
}

export function openTerminalSocket(
  url: string,
  credential: string,
  Socket: typeof WebSocket = WebSocket,
): WebSocket {
  return new Socket(url, ['memstack.auth', credential]);
}

function terminalLine(data: unknown): string {
  if (typeof data !== 'string') return '[binary terminal frame]';
  try {
    const parsed = JSON.parse(data);
    if (!parsed || typeof parsed !== 'object') return data;
    const record = parsed as Record<string, unknown>;
    if (record.type === 'output') return String(record.data ?? '');
    if (record.type === 'connected') {
      const sessionId = String(record.session_id ?? '');
      const cols = String(record.cols ?? '');
      const rows = String(record.rows ?? '');
      return `[connected] session=${sessionId} ${cols}x${rows}`;
    }
    if (record.type === 'error') return `[error] ${String(record.message ?? 'terminal failed')}`;
    return JSON.stringify(parsed);
  } catch {
    return data;
  }
}
