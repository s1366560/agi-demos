/**
 * TerminalImpl - Actual terminal implementation with xterm.js
 *
 * This file is dynamically imported to defer loading xterm.js
 * until the terminal is actually needed.
 */

import { useEffect, useRef, useCallback, useMemo } from 'react';

import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { Terminal } from '@xterm/xterm';

import { useThemeColors } from '../../../hooks/useThemeColor';
import { createWebSocketUrl } from '../../../services/client/urlUtils';
import { getAuthToken } from '../../../utils/tokenResolver';

interface TerminalMessage {
  type: 'input' | 'output' | 'resize' | 'error' | 'connected' | 'pong';
  data?: string | undefined;
  message?: string | undefined;
  session_id?: string | undefined;
  cols?: number | undefined;
  rows?: number | undefined;
}

interface TerminalImplProps {
  sandboxId: string;
  projectId?: string | undefined;
  sessionId?: string | undefined;
  onConnect: (sessionId: string) => void;
  onDisconnect: () => void;
  onError: (error: string) => void;
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  isFullscreen: boolean;
}

// Token map for terminal theme colors (resolved reactively via useThemeColors)
const TERMINAL_TOKEN_MAP = {
  background: '--color-background-dark',
  foreground: '--color-text-inverse',
  cursor: '--color-primary',
  cursorAccent: '--color-background-dark',
  selectionBackground: '--color-primary-light',
  black: '--color-background-dark',
  red: '--color-error',
  green: '--color-success',
  yellow: '--color-warning',
  blue: '--color-info',
  magenta: '--color-tile-purple',
  cyan: '--color-tile-cyan',
  white: '--color-text-inverse',
  brightBlack: '--color-text-muted',
  brightRed: '--color-error-light',
  brightGreen: '--color-success-light',
  brightYellow: '--color-warning-light',
  brightBlue: '--color-info-light',
  brightMagenta: '--color-tile-pink',
  brightCyan: '--color-tile-cyan',
  brightWhite: '--color-text-inverse',
} as const;

// Fallback hex values (original palette) for tokens that may not resolve
const TERMINAL_FALLBACKS: Record<string, string> = {
  background: '#141416',
  foreground: '#e8eaed',
  cursor: '#1e3fae',
  cursorAccent: '#141416',
  selectionBackground: '#3b5fc9',
  black: '#141416',
  red: '#ef4444',
  green: '#10b981',
  yellow: '#f59e0b',
  blue: '#3b82f6',
  magenta: '#8b5cf6',
  cyan: '#06b6d4',
  white: '#e8eaed',
  brightBlack: '#7d8599',
  brightRed: '#fee2e2',
  brightGreen: '#d1fae5',
  brightYellow: '#fef3c7',
  brightBlue: '#dbeafe',
  brightMagenta: '#ec4899',
  brightCyan: '#06b6d4',
  brightWhite: '#e8eaed',
};

export function TerminalImpl({
  sandboxId,
  projectId,
  sessionId,
  onConnect,
  onDisconnect,
  onError,
  isFullscreen,
}: TerminalImplProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const terminalInstance = useRef<Terminal | null>(null);
  const fitAddon = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Ref to hold connect function for use in onclose callback
  const connectRef = useRef<() => Promise<void>>(() => Promise.resolve());

  const resolvedColors = useThemeColors(TERMINAL_TOKEN_MAP);

  const terminalTheme = useMemo(() => {
    const theme: Record<string, string> = {};
    for (const key of Object.keys(TERMINAL_TOKEN_MAP) as Array<keyof typeof TERMINAL_TOKEN_MAP>) {
      theme[key] = resolvedColors[key] || TERMINAL_FALLBACKS[key] || '';
    }
    return theme;
  }, [resolvedColors]);

  const terminalThemeRef = useRef(terminalTheme);
  useEffect(() => {
    terminalThemeRef.current = terminalTheme;
  });

  // Get WebSocket URL using centralized utility
  // Use project-scoped WebSocket proxy endpoint if projectId is available
  const getWsUrl = useCallback(() => {
    // Get token for WebSocket authentication using centralized resolver
    const token = getAuthToken();
    const params: Record<string, string> = {};
    if (sessionId) {
      params.session_id = sessionId;
    }
    if (token) {
      params.token = token;
    }

    if (projectId) {
      // New project-scoped terminal WebSocket proxy
      return createWebSocketUrl(
        `/projects/${projectId}/sandbox/terminal/proxy/ws`,
        Object.keys(params).length > 0 ? params : undefined
      );
    }
    // Fallback to legacy sandbox endpoint
    return createWebSocketUrl(
      `/terminal/${sandboxId}/ws`,
      Object.keys(params).length > 0 ? params : undefined
    );
  }, [projectId, sandboxId, sessionId]);

  // Initialize terminal
  const initTerminal = useCallback(() => {
    if (!terminalRef.current || terminalInstance.current) return;

    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: terminalThemeRef.current,
      allowProposedApi: true,
    });

    const fit = new FitAddon();
    const webLinks = new WebLinksAddon();

    terminal.loadAddon(fit);
    terminal.loadAddon(webLinks);

    terminal.open(terminalRef.current);
    fit.fit();

    terminalInstance.current = terminal;
    fitAddon.current = fit;

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      if (fitAddon.current) {
        fitAddon.current.fit();
        // Send resize to server
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(
            JSON.stringify({
              type: 'resize',
              cols: terminal.cols,
              rows: terminal.rows,
            })
          );
        }
      }
    });
    resizeObserver.observe(terminalRef.current);

    return () => {
      resizeObserver.disconnect();
      terminal.dispose();
      terminalInstance.current = null;
      fitAddon.current = null;
    };
  }, []);

  // Connect WebSocket
  const connect = useCallback(async () => {
    // Check if WebSocket is available (not in test environment) and already open
    if (typeof WebSocket === 'undefined') return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(getWsUrl());

    ws.onopen = () => {};

    ws.onmessage = (event) => {
      try {
        const msg: TerminalMessage = JSON.parse(event.data);

        switch (msg.type) {
          case 'connected':
            if (msg.session_id) {
              onConnect(msg.session_id);
            }
            // Write welcome message
            terminalInstance.current?.writeln('\x1b[32m✓ Connected to sandbox terminal\x1b[0m');
            terminalInstance.current?.writeln('');
            break;

          case 'output':
            if (msg.data) {
              terminalInstance.current?.write(msg.data);
            }
            break;

          case 'error':
            onError(msg.message || 'Unknown error');
            break;

          case 'pong':
            // Heartbeat response
            break;
        }
      } catch (e) {
        console.error('[Terminal] Failed to parse message:', e);
      }
    };

    ws.onerror = (event) => {
      console.error('[Terminal] WebSocket error:', event);
      onError('Connection error');
    };

    ws.onclose = (event) => {
      onDisconnect();

      // Auto-reconnect on abnormal close
      if (event.code !== 1000 && event.code !== 1001) {
        reconnectTimeoutRef.current = setTimeout(() => {
          connectRef.current();
        }, 3000);
      }
    };

    wsRef.current = ws;

    // Setup terminal input handler
    if (terminalInstance.current) {
      terminalInstance.current.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'input', data }));
        }
      });
    }
  }, [getWsUrl, onConnect, onDisconnect, onError]);

  // Keep connectRef updated
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  // Disconnect
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnect');
      wsRef.current = null;
    }
  }, []);

  // Initialize
  useEffect(() => {
    const cleanup = initTerminal();
    return () => {
      cleanup?.();
      disconnect();
    };
  }, [initTerminal, disconnect]);

  // Auto-connect when terminal is ready
  useEffect(() => {
    if (terminalInstance.current && wsRef.current?.readyState === undefined) {
      // Use requestAnimationFrame to defer state update and avoid cascading renders
      const rafId = requestAnimationFrame(() => {
        connect();
      });
      return () => {
        cancelAnimationFrame(rafId);
      };
    }
    return undefined;
  }, [connect]);

  // Handle fullscreen resize
  useEffect(() => {
    if (fitAddon.current) {
      // Fit terminal after state change
      setTimeout(() => {
        fitAddon.current?.fit();
      }, 100);
    }
  }, [isFullscreen]);

  useEffect(() => {
    if (terminalInstance.current) {
      terminalInstance.current.options.theme = terminalTheme;
    }
  }, [terminalTheme]);

  // Heartbeat
  useEffect(() => {
    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);

    return () => {
      clearInterval(interval);
    };
  }, []);

  return <div ref={terminalRef} className="h-full w-full" style={{ padding: '4px' }} />;
}

export default TerminalImpl;
