/**
 * NoVNCViewer - Direct noVNC client for sandbox desktop access
 *
 * Uses @novnc/novnc RFB class for WebSocket-based VNC connection
 * with clipboard sync, keyboard handling, and viewport scaling.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  CopyOutlined,
  DisconnectOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  LinkOutlined,
  LoadingOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { Alert, Button, Input, Space, Spin, Tooltip } from 'antd';
// @ts-expect-error -- vendored noVNC ESM source (no TS declarations)
import RFB from '../../../vendor/novnc/core/rfb.js';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface NoVNCViewerProps {
  /** WebSocket URL for VNC connection (ws://...) */
  wsUrl: string;
  /** Called when connection is established */
  onConnect?: () => void;
  /** Called when connection is lost */
  onDisconnect?: (reason?: string) => void;
  /** Called on connection error */
  onError?: (error: string) => void;
  /** View-only mode (no input) */
  viewOnly?: boolean;
  /** Scale viewport to fit container */
  scaleViewport?: boolean;
  /** Show toolbar */
  showToolbar?: boolean;
  /** Show clipboard panel */
  showClipboard?: boolean;
}

export function NoVNCViewer({
  wsUrl,
  onConnect,
  onDisconnect,
  onError,
  viewOnly = false,
  scaleViewport = true,
  showToolbar = true,
  showClipboard: initialShowClipboard = false,
}: NoVNCViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showClipboard, setShowClipboard] = useState(initialShowClipboard);
  const [clipboardText, setClipboardText] = useState('');
  const [remoteClipboard, setRemoteClipboard] = useState('');

  const disconnect = useCallback(() => {
    if (rfbRef.current) {
      try {
        rfbRef.current.disconnect();
      } catch {
        // ignore
      }
      rfbRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!containerRef.current || !wsUrl) return;

    disconnect();

    setConnectionState('connecting');
    setErrorMessage(null);

    try {
      const rfb = new RFB(containerRef.current, wsUrl, {
        wsProtocols: ['binary'],
      });

      rfb.viewOnly = viewOnly;
      rfb.scaleViewport = scaleViewport;
      rfb.resizeSession = false;
      rfb.showDotCursor = !viewOnly;
      rfb.focusOnClick = true;
      rfb.background = '#1a1a2e';
      rfb.qualityLevel = 6;
      rfb.compressionLevel = 2;

      rfb.addEventListener('connect', () => {
        setConnectionState('connected');
        setErrorMessage(null);
        onConnect?.();
      });

      rfb.addEventListener('disconnect', (e: Event) => {
        const detail = (e as CustomEvent).detail;
        setConnectionState('disconnected');
        rfbRef.current = null;
        if (detail?.clean) {
          onDisconnect?.();
        } else {
          const reason = 'Connection lost unexpectedly';
          setErrorMessage(reason);
          setConnectionState('error');
          onDisconnect?.(reason);
        }
      });

      rfb.addEventListener('credentialsrequired', () => {
        rfb.sendCredentials({ password: '' });
      });

      rfb.addEventListener('clipboard', (e: Event) => {
        const detail = (e as CustomEvent).detail;
        if (detail?.text) {
          setRemoteClipboard(detail.text);
          // Auto-copy to local clipboard
          navigator.clipboard?.writeText(detail.text).catch(() => {
            // Clipboard API may not be available
          });
        }
      });

      rfb.addEventListener('securityfailure', (e: Event) => {
        const detail = (e as CustomEvent).detail;
        const msg = `Security failure: ${detail?.reason || 'unknown'}`;
        setErrorMessage(msg);
        setConnectionState('error');
        onError?.(msg);
      });

      rfbRef.current = rfb;
    } catch (err) {
      const msg = `Failed to create VNC connection: ${err}`;
      setErrorMessage(msg);
      setConnectionState('error');
      onError?.(msg);
    }
  }, [wsUrl, viewOnly, scaleViewport, onConnect, onDisconnect, onError, disconnect]);

  // Connect when wsUrl changes
  useEffect(() => {
    if (wsUrl) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, [wsUrl, connect, disconnect]);

  // Handle fullscreen toggle
  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((prev) => !prev);
  }, []);

  // Send clipboard text to remote
  const sendClipboard = useCallback(() => {
    if (rfbRef.current && clipboardText) {
      rfbRef.current.clipboardPasteFrom(clipboardText);
    }
  }, [clipboardText]);

  // Paste from local clipboard
  const pasteFromLocal = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      setClipboardText(text);
      if (rfbRef.current && text) {
        rfbRef.current.clipboardPasteFrom(text);
      }
    } catch {
      // Clipboard API may not be available
    }
  }, []);

  const containerStyle: React.CSSProperties = {
    height: isFullscreen ? '100vh' : '100%',
    position: isFullscreen ? 'fixed' : 'relative',
    top: isFullscreen ? 0 : 'auto',
    left: isFullscreen ? 0 : 'auto',
    width: isFullscreen ? '100vw' : '100%',
    zIndex: isFullscreen ? 50 : 'auto',
  };

  const statusConfig: Record<ConnectionState, { color: string; text: string }> = {
    disconnected: { color: '#888', text: 'Disconnected' },
    connecting: { color: '#faad14', text: 'Connecting...' },
    connected: { color: '#52c41a', text: 'Connected' },
    error: { color: '#ff4d4f', text: 'Error' },
  };

  const status = statusConfig[connectionState];

  return (
    <div
      className={`flex flex-col bg-gray-900 ${isFullscreen ? 'fixed inset-0 z-50' : ''}`}
      style={containerStyle}
    >
      {/* Toolbar */}
      {showToolbar && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ backgroundColor: status.color }}
            />
            <span className="text-xs text-gray-400">{status.text}</span>
          </div>

          <Space size="small">
            <Tooltip title="Sync clipboard">
              <Button
                type="text"
                size="small"
                icon={<CopyOutlined />}
                onClick={() => setShowClipboard((prev) => !prev)}
                className={`text-gray-400 hover:text-white ${showClipboard ? '!text-blue-400' : ''}`}
                aria-label="Toggle clipboard"
              />
            </Tooltip>
            <Tooltip title="Reconnect">
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                onClick={connect}
                disabled={connectionState === 'connecting'}
                className="text-gray-400 hover:text-white"
                aria-label="Reconnect"
              />
            </Tooltip>
            <Tooltip title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}>
              <Button
                type="text"
                size="small"
                icon={isFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                onClick={toggleFullscreen}
                className="text-gray-400 hover:text-white"
                aria-label={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
              />
            </Tooltip>
          </Space>
        </div>
      )}

      {/* Clipboard Panel */}
      {showClipboard && (
        <div className="px-3 py-2 bg-gray-800 border-b border-gray-700">
          <div className="flex gap-2 items-center">
            <Input.TextArea
              value={clipboardText}
              onChange={(e) => setClipboardText(e.target.value)}
              placeholder="Paste text here to send to remote desktop..."
              autoSize={{ minRows: 1, maxRows: 3 }}
              className="flex-1 !text-xs"
              size="small"
            />
            <Space direction="vertical" size={2}>
              <Button size="small" onClick={sendClipboard} icon={<LinkOutlined />}>
                Send
              </Button>
              <Button size="small" onClick={pasteFromLocal} icon={<CopyOutlined />}>
                Paste
              </Button>
            </Space>
          </div>
          {remoteClipboard && (
            <div className="mt-1 text-xs text-gray-500 truncate">
              Remote: {remoteClipboard.slice(0, 100)}
            </div>
          )}
        </div>
      )}

      {/* VNC Canvas Container */}
      <div className="flex-1 relative bg-black overflow-hidden">
        {connectionState === 'connecting' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/50 z-10">
            <Spin indicator={<LoadingOutlined style={{ fontSize: 32 }} spin />} />
            <span className="text-white text-sm">Connecting to desktop...</span>
          </div>
        )}

        {connectionState === 'error' && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <Alert
              type="error"
              message="Connection Failed"
              description={errorMessage}
              showIcon
              icon={<DisconnectOutlined />}
              action={
                <Button size="small" onClick={connect}>
                  Retry
                </Button>
              }
              className="m-4 max-w-md"
            />
          </div>
        )}

        {connectionState === 'disconnected' && !errorMessage && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 z-10">
            <DisconnectOutlined className="text-4xl text-gray-500" />
            <span className="text-gray-400">Desktop disconnected</span>
            <Button size="small" onClick={connect}>
              Reconnect
            </Button>
          </div>
        )}

        <div
          ref={containerRef}
          className="w-full h-full"
          style={{ cursor: viewOnly ? 'default' : 'auto' }}
        />
      </div>
    </div>
  );
}

export default NoVNCViewer;
