/**
 * TerminalImpl - Actual terminal implementation with xterm.js
 *
 * This file is dynamically imported to defer loading xterm.js
 * until the terminal is actually needed.
 */

import { useEffect, useRef, useCallback } from "react";

import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal } from "@xterm/xterm";

import { createWebSocketUrl } from "../../../services/client/urlUtils";

interface TerminalMessage {
  type: "input" | "output" | "resize" | "error" | "connected" | "pong";
  data?: string;
  message?: string;
  session_id?: string;
  cols?: number;
  rows?: number;
}

interface TerminalImplProps {
  sandboxId: string;
  sessionId?: string;
  onConnect: (sessionId: string) => void;
  onDisconnect: () => void;
  onError: (error: string) => void;
  status: "disconnected" | "connecting" | "connected" | "error";
  isFullscreen: boolean;
}

export function TerminalImpl({
  sandboxId,
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

  // Get WebSocket URL using centralized utility
  const getWsUrl = useCallback(() => {
    return createWebSocketUrl(
      `/terminal/${sandboxId}/ws`,
      sessionId ? { session_id: sessionId } : undefined
    );
  }, [sandboxId, sessionId]);

  // Initialize terminal
  const initTerminal = useCallback(() => {
    if (!terminalRef.current || terminalInstance.current) return;

    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: {
        background: "#1e1e1e",
        foreground: "#d4d4d4",
        cursor: "#d4d4d4",
        cursorAccent: "#1e1e1e",
        selectionBackground: "#264f78",
        black: "#000000",
        red: "#cd3131",
        green: "#0dbc79",
        yellow: "#e5e510",
        blue: "#2472c8",
        magenta: "#bc3fbc",
        cyan: "#11a8cd",
        white: "#e5e5e5",
        brightBlack: "#666666",
        brightRed: "#f14c4c",
        brightGreen: "#23d18b",
        brightYellow: "#f5f543",
        brightBlue: "#3b8eea",
        brightMagenta: "#d670d6",
        brightCyan: "#29b8db",
        brightWhite: "#e5e5e5",
      },
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
              type: "resize",
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
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(getWsUrl());

    ws.onopen = () => {
      console.log("[Terminal] WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg: TerminalMessage = JSON.parse(event.data);

        switch (msg.type) {
          case "connected":
            if (msg.session_id) {
              onConnect(msg.session_id);
            }
            // Write welcome message
            terminalInstance.current?.writeln(
              "\x1b[32m✓ Connected to sandbox terminal\x1b[0m"
            );
            terminalInstance.current?.writeln("");
            break;

          case "output":
            if (msg.data) {
              terminalInstance.current?.write(msg.data);
            }
            break;

          case "error":
            onError(msg.message || "Unknown error");
            break;

          case "pong":
            // Heartbeat response
            break;
        }
      } catch (e) {
        console.error("[Terminal] Failed to parse message:", e);
      }
    };

    ws.onerror = (event) => {
      console.error("[Terminal] WebSocket error:", event);
      onError("Connection error");
    };

    ws.onclose = (event) => {
      console.log("[Terminal] WebSocket closed:", event.code, event.reason);
      onDisconnect();

      // Auto-reconnect on abnormal close
      if (event.code !== 1000 && event.code !== 1001) {
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log("[Terminal] Attempting reconnect...");
          connectRef.current();
        }, 3000);
      }
    };

    wsRef.current = ws;

    // Setup terminal input handler
    if (terminalInstance.current) {
      terminalInstance.current.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "input", data }));
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
      wsRef.current.close(1000, "User disconnect");
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
      return () => cancelAnimationFrame(rafId);
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

  // Heartbeat
  useEffect(() => {
    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div
      ref={terminalRef}
      className="h-full w-full"
      style={{ padding: "4px" }}
    />
  );
}

export default TerminalImpl;
