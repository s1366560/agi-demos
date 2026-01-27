/**
 * SandboxTerminal - Interactive terminal component using xterm.js
 *
 * Connects to backend terminal WebSocket and provides full terminal emulation
 * for interacting with sandbox containers.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Spin, Alert, Button } from "antd";
import {
  ReloadOutlined,
  ExpandOutlined,
  CompressOutlined,
} from "@ant-design/icons";
import { createWebSocketUrl } from "../../../services/client/urlUtils";

import "@xterm/xterm/css/xterm.css";

export interface SandboxTerminalProps {
  /** Sandbox container ID */
  sandboxId: string;
  /** Optional existing session ID to reconnect */
  sessionId?: string;
  /** Called when terminal connects */
  onConnect?: (sessionId: string) => void;
  /** Called when terminal disconnects */
  onDisconnect?: () => void;
  /** Called on terminal error */
  onError?: (error: string) => void;
  /** Terminal height (default: 100%) */
  height?: string | number;
  /** Show toolbar (default: true) */
  showToolbar?: boolean;
}

type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

interface TerminalMessage {
  type: "input" | "output" | "resize" | "error" | "connected" | "pong";
  data?: string;
  message?: string;
  session_id?: string;
  cols?: number;
  rows?: number;
}

export function SandboxTerminal({
  sandboxId,
  sessionId: initialSessionId,
  onConnect,
  onDisconnect,
  onError,
  height = "100%",
  showToolbar = true,
}: SandboxTerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const terminalInstance = useRef<Terminal | null>(null);
  const fitAddon = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [sessionId, setSessionId] = useState<string | null>(
    initialSessionId || null
  );
  const [error, setError] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Ref to hold connect function for use in onclose callback
  const connectRef = useRef<() => void>(() => {});

  // Get WebSocket URL using centralized utility
  const getWsUrl = useCallback(() => {
    return createWebSocketUrl(`/terminal/${sandboxId}/ws`, sessionId ? { session_id: sessionId } : undefined);
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
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setStatus("connecting");
    setError(null);

    const ws = new WebSocket(getWsUrl());

    ws.onopen = () => {
      console.log("[Terminal] WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg: TerminalMessage = JSON.parse(event.data);

        switch (msg.type) {
          case "connected":
            setStatus("connected");
            if (msg.session_id) {
              setSessionId(msg.session_id);
              onConnect?.(msg.session_id);
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
            setError(msg.message || "Unknown error");
            setStatus("error");
            onError?.(msg.message || "Unknown error");
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
      setError("Connection error");
      setStatus("error");
    };

    ws.onclose = (event) => {
      console.log("[Terminal] WebSocket closed:", event.code, event.reason);
      setStatus("disconnected");
      onDisconnect?.();

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

    setStatus("disconnected");
  }, []);

  // Reconnect
  const reconnect = useCallback(() => {
    disconnect();
    setSessionId(null);
    setTimeout(connect, 100);
  }, [disconnect, connect]);

  // Toggle fullscreen
  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((prev) => !prev);
    // Fit terminal after state change
    setTimeout(() => {
      fitAddon.current?.fit();
    }, 100);
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
    if (terminalInstance.current && status === "disconnected") {
      // Use requestAnimationFrame to defer state update and avoid cascading renders
      const rafId = requestAnimationFrame(() => {
        connect();
      });
      return () => cancelAnimationFrame(rafId);
    }
    return undefined;
  }, [connect, status]);

  // Heartbeat
  useEffect(() => {
    if (status !== "connected") return;

    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);

    return () => clearInterval(interval);
  }, [status]);

  return (
    <div
      className={`flex flex-col ${isFullscreen ? "fixed inset-0 z-50 bg-[#1e1e1e]" : ""}`}
      style={{ height: isFullscreen ? "100vh" : height }}
    >
      {/* Toolbar */}
      {showToolbar && (
        <div className="flex items-center justify-between px-3 py-2 bg-[#252526] border-b border-[#3c3c3c]">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                status === "connected"
                  ? "bg-green-500"
                  : status === "connecting"
                    ? "bg-yellow-500 animate-pulse"
                    : status === "error"
                      ? "bg-red-500"
                      : "bg-gray-500"
              }`}
            />
            <span className="text-xs text-gray-400">
              {status === "connected"
                ? `Terminal (${sessionId?.slice(0, 8)})`
                : status === "connecting"
                  ? "Connecting..."
                  : status === "error"
                    ? "Error"
                    : "Disconnected"}
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
              title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            />
          </div>
        </div>
      )}

      {/* Terminal */}
      <div className="flex-1 relative">
        {status === "connecting" && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#1e1e1e] z-10">
            <Spin tip="Connecting to terminal..." />
          </div>
        )}

        {error && status === "error" && (
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

        <div
          ref={terminalRef}
          className="h-full w-full"
          style={{ padding: "4px" }}
        />
      </div>
    </div>
  );
}

export default SandboxTerminal;
