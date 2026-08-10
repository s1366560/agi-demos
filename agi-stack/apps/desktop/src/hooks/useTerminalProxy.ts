import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  CLOUD_SOCKET_OPEN,
  createCloudSocketBridge,
  desktopCloudSocketTransport,
} from '../api/cloudSocketBridge';

import {
  acceptTerminalSequence,
  terminalAcknowledgementMatches,
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

const TERMINAL_CLIENT_FRAME_BYTES = 128 * 1024;
const TERMINAL_AGGREGATE_BYTES = 256 * 1024;

type TerminalCloudSocketAuthority = Readonly<{
  tenantId: string;
  projectId: string;
  workspaceId: string | null;
  conversationId: string | null;
}>;

export function useTerminalProxy(
  url: string | null,
  credential: string,
  launchCapability: string,
  recovery?: {
    session: TerminalSessionV2 | null;
    onRefetchRun: (reasonCode: string) => void;
  },
  cloudAuthority?: TerminalCloudSocketAuthority,
): TerminalProxyState {
  const socketRef = useRef<WebSocket | null>(null);
  const generationRef = useRef(0);
  const pendingLinesRef = useRef<string[]>([]);
  const linesFlushCancelRef = useRef<(() => void) | null>(null);
  const [status, setStatus] = useState<TerminalConnectionStatus>('idle');
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cloudSocketTransport = useMemo(
    () => (cloudAuthority ? desktopCloudSocketTransport() : null),
    [
      cloudAuthority?.conversationId,
      cloudAuthority?.projectId,
      cloudAuthority?.tenantId,
      cloudAuthority?.workspaceId,
    ],
  );

  const flushPendingLines = useCallback(() => {
    linesFlushCancelRef.current = null;
    const pending = pendingLinesRef.current;
    if (!pending.length) return;
    pendingLinesRef.current = [];
    setLines((current) => appendTerminalLinesBounded(current, pending));
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
    const authenticationAvailable = Boolean(credential) || cloudSocketTransport !== null;
    if (!url || !authenticationAvailable) {
      setStatus(url && !authenticationAvailable ? 'error' : 'idle');
      setError(url && !authenticationAvailable ? 'terminal_credential_unavailable' : null);
      return;
    }

    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempts = 0;
    let lastSequence = 0;
    let disconnectEvent: TerminalDisconnectEvent | null = null;
    const recoveryConfig = recovery;

    const connect = () => {
      if (disposed || generationRef.current !== generation) return;
      setStatus('connecting');
      const target = new URL(url);
      if (Number.isSafeInteger(lastSequence) && lastSequence > 0) {
        target.searchParams.set('after_sequence', String(lastSequence));
      }
      const session = recoveryConfig?.session ?? null;
      const sessionId = session?.session_id ?? target.searchParams.get('session_id') ?? '';
      const socket =
        cloudSocketTransport && cloudAuthority
          ? (createCloudSocketBridge(
              {
                kind: 'terminal',
                url: target.toString(),
                scope: {
                  tenant_id: cloudAuthority.tenantId,
                  project_id: cloudAuthority.projectId,
                  workspace_id: cloudAuthority.workspaceId,
                  conversation_id: cloudAuthority.conversationId,
                },
                terminal: {
                  session_id: sessionId,
                  resume_token: session?.resume_token ?? null,
                },
              },
              cloudSocketTransport,
            ) as unknown as WebSocket)
          : openTerminalSocket(
              url,
              credential,
              launchCapability,
              WebSocket,
              session?.resume_token ?? '',
              lastSequence,
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
        if (
          typeof message.data === 'string' &&
          utf8Bytes(message.data) > TERMINAL_CLIENT_FRAME_BYTES
        ) {
          disconnectEvent = { kind: 'output_gap' };
          setStatus('error');
          setError('terminal_output_gap');
          socket.close();
          return;
        }
        const frame = terminalFrame(message.data, Boolean(recoveryConfig?.session));
        if (
          frame.acknowledged_sequence !== undefined &&
          !terminalAcknowledgementMatches(lastSequence, frame.acknowledged_sequence)
        ) {
          disconnectEvent = { kind: 'output_gap' };
          setStatus('error');
          setError('terminal_output_gap');
          socket.close();
          return;
        }
        if (frame.sequence !== undefined) {
          const acceptance = acceptTerminalSequence(lastSequence, frame.sequence);
          if (acceptance.gap) {
            disconnectEvent = { kind: 'output_gap' };
            setStatus('error');
            setError('terminal_output_gap');
            socket.close();
            return;
          }
          if (!acceptance.accepted) return;
          lastSequence = acceptance.next_sequence;
        }
        if (frame.line !== null) {
          const pendingBytes =
            pendingLinesRef.current.reduce((total, line) => total + utf8Bytes(line), 0) +
            utf8Bytes(frame.line);
          if (pendingBytes > TERMINAL_AGGREGATE_BYTES) {
            disconnectEvent = { kind: 'output_gap' };
            setStatus('error');
            setError('terminal_output_gap');
            socket.close();
            return;
          }
          pendingLinesRef.current.push(frame.line);
          scheduleLinesFlush();
        }
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
  }, [
    cloudAuthority,
    cloudSocketTransport,
    credential,
    launchCapability,
    recovery,
    scheduleLinesFlush,
    url,
  ]);

  return {
    status,
    connected: status === 'connected',
    lines,
    error,
    sendInput(data: string) {
      if (socketRef.current?.readyState === CLOUD_SOCKET_OPEN) {
        socketRef.current.send(JSON.stringify({ type: 'input', data }));
        return true;
      }
      return false;
    },
    resize(cols: number, rows: number) {
      if (socketRef.current?.readyState === CLOUD_SOCKET_OPEN) {
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
  afterSequence = 0,
): WebSocket {
  const protocols = launchCapability
    ? ['memstack.launch', launchCapability, 'memstack.auth', credential]
    : ['memstack.auth', credential];
  if (resumeToken) protocols.push('memstack.terminal-v2', resumeToken);
  const target = new URL(url);
  if (Number.isSafeInteger(afterSequence) && afterSequence > 0) {
    target.searchParams.set('after_sequence', String(afterSequence));
  }
  return new Socket(target.toString(), protocols);
}

export function terminalFrame(data: unknown, requireSequence = false): {
  line: string | null;
  error: string | null;
  disconnect?: TerminalDisconnectEvent;
  sequence?: number;
  acknowledged_sequence?: number;
} {
  if (typeof data !== 'string') return { line: '[binary terminal frame]', error: null };
  try {
    const parsed = JSON.parse(data);
    if (!parsed || typeof parsed !== 'object') return { line: data, error: null };
    const record = parsed as Record<string, unknown>;
    if (record.type === 'output') {
      if (!requireSequence && record.sequence === undefined && typeof record.data === 'string') {
        return { line: record.data, error: null };
      }
      if (
        !Number.isSafeInteger(record.sequence) ||
        Number(record.sequence) < 1 ||
        typeof record.data !== 'string'
      ) {
        return {
          line: null,
          error: 'terminal_output_gap',
          disconnect: { kind: 'output_gap' },
        };
      }
      return {
        line: record.data,
        error: null,
        sequence: Number(record.sequence),
      };
    }
    if (record.type === 'ack') {
      if (!Number.isSafeInteger(record.after_sequence) || Number(record.after_sequence) < 0) {
        return {
          line: null,
          error: 'terminal_output_gap',
          disconnect: { kind: 'output_gap' },
        };
      }
      return {
        line: null,
        error: null,
        acknowledged_sequence: Number(record.after_sequence),
      };
    }
    if (record.type === 'connected') {
      if (requireSequence) return { line: null, error: null };
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
    if (record.type === 'terminal_output_gap') {
      return {
        line: null,
        error: 'terminal_output_gap',
        disconnect: { kind: 'output_gap' },
      };
    }
    if (record.type === 'terminal_input_overload') {
      return {
        line: null,
        error: 'terminal_input_overload',
        disconnect: { kind: 'input_overload' },
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

export function appendTerminalLinesBounded(
  current: string[],
  pending: string[],
  maxBytes = TERMINAL_AGGREGATE_BYTES,
): string[] {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) return [];
  const combined = [...current, ...pending];
  const retained: string[] = [];
  let retainedBytes = 0;
  for (let index = combined.length - 1; index >= 0; index -= 1) {
    const line = combined[index];
    const lineBytes = utf8Bytes(line);
    if (lineBytes > maxBytes || retainedBytes + lineBytes > maxBytes) break;
    retained.unshift(line);
    retainedBytes += lineBytes;
  }
  return retained.slice(-300);
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}
