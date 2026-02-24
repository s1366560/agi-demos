/**
 * KasmVNCViewer - Direct KasmVNC RFB client for desktop access
 *
 * Uses KasmVNC's own noVNC fork (vendored) which supports KasmVNC's
 * proprietary protocol extensions (WebP encoding, QOI, etc.).
 * Standard noVNC cannot handle these extensions and disconnects.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  AudioMutedOutlined,
  AudioOutlined,
  DesktopOutlined,
  DisconnectOutlined,
  ExpandOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  LoadingOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { Button, Select, Space, Spin, Tooltip } from 'antd';

// @ts-expect-error -- vendored KasmVNC noVNC fork
import MouseButtonMapper, { XVNC_BUTTONS } from '@/vendor/kasmvnc/core/mousebuttonmapper.js';
// @ts-expect-error -- vendored KasmVNC noVNC fork (ES modules, no TS declarations)
import RFB from '@/vendor/kasmvnc/core/rfb.js';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'error';

const RESOLUTION_PRESETS = [
  { label: 'Auto (fit panel)', value: 'auto' },
  { label: '1280x720 (HD)', value: '1280x720' },
  { label: '1600x900', value: '1600x900' },
  { label: '1920x1080 (FHD)', value: '1920x1080' },
  { label: '2560x1440 (QHD)', value: '2560x1440' },
];

export interface KasmVNCViewerProps {
  /** WebSocket URL to the KasmVNC proxy endpoint */
  wsUrl: string;
  /** Current resolution */
  resolution?: string;
  /** Whether audio is enabled */
  audioEnabled?: boolean;
  /** Whether dynamic resize is supported */
  dynamicResize?: boolean;
  /** Called when connection is established */
  onConnect?: () => void;
  /** Called when connection is lost */
  onDisconnect?: (reason?: string) => void;
  /** Called on connection error */
  onError?: (error: string) => void;
  /** Called to change resolution */
  onResolutionChange?: (resolution: string) => void;
  /** Show toolbar */
  showToolbar?: boolean;
}

export function KasmVNCViewer({
  wsUrl,
  resolution = 'auto',
  audioEnabled = false,
  dynamicResize = true,
  onConnect,
  onDisconnect,
  onError,
  onResolutionChange,
  showToolbar = true,
}: KasmVNCViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<InstanceType<typeof RFB> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const intentionalDisconnectRef = useRef(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isMuted, setIsMuted] = useState(!audioEnabled);
  const [currentResolution, setCurrentResolution] = useState(resolution);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  // Safely disconnect RFB, handling the case where it hasn't finished initializing
  const safeDisconnect = useCallback((rfb: InstanceType<typeof RFB> | null) => {
    if (!rfb) return;
    try {
      // KasmVNC RFB defers state transition to 'connecting' via setTimeout.
      // If React StrictMode unmounts before that fires, state is still ''.
      // Check internal state to avoid "Bad transition" error.
      const state = rfb._rfbConnectionState;
      if (state === 'connected' || state === 'connecting') {
        rfb.disconnect();
      } else {
        // Force-close the underlying WebSocket if state hasn't initialized
        rfb._sock?.close();
      }
    } catch {
      // ignore cleanup errors
    }
  }, []);

  // Connect to the VNC server via KasmVNC RFB
  const connectRFB = useCallback(() => {
    const target = canvasContainerRef.current;
    if (!target || !wsUrl) return;

    // Clean up existing connection
    if (rfbRef.current) {
      intentionalDisconnectRef.current = true;
      safeDisconnect(rfbRef.current);
      rfbRef.current = null;
    }

    // Clear canvas container (RFB appends its own canvas)
    target.innerHTML = '';
    setConnectionState('connecting');
    intentionalDisconnectRef.current = false;

    try {
      // KasmVNC RFB constructor: (target, touchInput, url, options)
      // touchInput is required for keyboard input (used by Keyboard class)
      const touchInput = document.createElement('textarea');
      touchInput.style.cssText =
        'position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;';
      touchInput.setAttribute('autocapitalize', 'off');
      touchInput.setAttribute('autocomplete', 'off');
      touchInput.setAttribute('spellcheck', 'false');
      touchInput.setAttribute('tabindex', '-1');
      target.appendChild(touchInput);

      const rfb = new RFB(target, touchInput, wsUrl, {
        wsProtocols: ['binary'],
        shared: true,
      });

      const isAuto = currentResolution === 'auto';
      rfb.scaleViewport = true;
      rfb.resizeSession = isAuto && dynamicResize;
      rfb.clipViewport = false;
      rfb.background = '#000000';
      rfb.qualityLevel = 8;

      // Initialize mouse button mapper (required by KasmVNC's RFB)
      const mapper = new MouseButtonMapper();
      mapper.set(0, XVNC_BUTTONS.LEFT_BUTTON);
      mapper.set(1, XVNC_BUTTONS.MIDDLE_BUTTON);
      mapper.set(2, XVNC_BUTTONS.RIGHT_BUTTON);
      mapper.set(3, XVNC_BUTTONS.BACK_BUTTON);
      mapper.set(4, XVNC_BUTTONS.FORWARD_BUTTON);
      rfb.mouseButtonMapper = mapper;

      rfb.addEventListener('connect', () => {
        setConnectionState('connected');
        reconnectAttemptRef.current = 0;
        onConnect?.();
      });

      rfb.addEventListener('disconnect', (e: { detail: { clean: boolean; reason?: string } }) => {
        console.warn('[KasmVNC] Disconnected', {
          clean: e.detail.clean,
          reason: e.detail.reason || '(no reason)',
        });
        rfbRef.current = null;

        if (intentionalDisconnectRef.current) {
          setConnectionState('disconnected');
          onDisconnect?.();
          return;
        }

        // Auto-reconnect on unexpected disconnect
        const attempt = reconnectAttemptRef.current;
        const MAX_RECONNECT_ATTEMPTS = 10;
        if (attempt < MAX_RECONNECT_ATTEMPTS) {
          const delay = Math.min(1000 * Math.pow(1.5, attempt), 15000);
          reconnectAttemptRef.current = attempt + 1;
          setConnectionState('connecting');
          console.info(`[KasmVNC] Auto-reconnect attempt ${attempt + 1} in ${delay}ms`);
          reconnectTimerRef.current = setTimeout(() => {
            connectRFB();
          }, delay);
        } else {
          setConnectionState('error');
          onError?.('Connection lost after max retries');
          onDisconnect?.('Connection lost');
        }
      });

      rfb.addEventListener('credentialsrequired', () => {
        // KasmVNC with -disableBasicAuth should not need credentials
        // but send empty password just in case
        rfb.sendCredentials({ password: '' });
      });

      rfb.addEventListener('desktopname', (e: { detail: { name: string } }) => {
        // Desktop name received (informational)
        void e;
      });

      rfb.addEventListener('clipboard', (e: { detail: { text: string } }) => {
        // Server clipboard -> browser clipboard
        navigator.clipboard?.writeText(e.detail.text).catch(() => {
          // clipboard write may fail without user gesture
        });
      });

      rfbRef.current = rfb;
    } catch (err) {
      setConnectionState('error');
      onError?.(`Failed to connect: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [
    wsUrl,
    currentResolution,
    dynamicResize,
    onConnect,
    onDisconnect,
    onError,
    safeDisconnect,
  ]);

  // Connect on mount and when wsUrl changes
  useEffect(() => {
    if (!wsUrl) return;
    connectRFB();
    return () => {
      clearReconnectTimer();
      intentionalDisconnectRef.current = true;
      safeDisconnect(rfbRef.current);
      rfbRef.current = null;
    };
    // Only reconnect when wsUrl changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsUrl]);

  // Update RFB resize mode when resolution changes (no reconnect needed)
  useEffect(() => {
    const rfb = rfbRef.current;
    if (!rfb) return;
    const isAuto = currentResolution === 'auto';
    rfb.resizeSession = isAuto && dynamicResize;
    rfb.scaleViewport = true;
  }, [currentResolution, dynamicResize]);

  // Handle fullscreen toggle
  const toggleFullscreen = useCallback(async () => {
    if (!containerRef.current) return;
    try {
      if (!document.fullscreenElement) {
        await containerRef.current.requestFullscreen();
        setIsFullscreen(true);
      } else {
        await document.exitFullscreen();
        setIsFullscreen(false);
      }
    } catch {
      setIsFullscreen((prev) => !prev);
    }
  }, []);

  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => { document.removeEventListener('fullscreenchange', handleFullscreenChange); };
  }, []);

  // Handle resolution change
  const handleResolutionChange = useCallback(
    (value: string) => {
      setCurrentResolution(value);
      onResolutionChange?.(value);
    },
    [onResolutionChange]
  );

  // Reconnect (manual)
  const handleReconnect = useCallback(() => {
    clearReconnectTimer();
    reconnectAttemptRef.current = 0;
    connectRFB();
  }, [connectRFB, clearReconnectTimer]);

  const containerStyle: React.CSSProperties = isFullscreen
    ? { position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', zIndex: 50 }
    : { height: '100%', position: 'relative', width: '100%' };

  const statusConfig: Record<ConnectionState, { color: string; text: string }> = {
    disconnected: { color: '#888', text: 'Disconnected' },
    connecting: { color: '#faad14', text: 'Connecting...' },
    connected: { color: '#52c41a', text: 'Connected' },
    error: { color: '#ff4d4f', text: 'Error' },
  };

  const status = statusConfig[connectionState];

  return (
    <div
      ref={containerRef}
      className={`flex flex-col bg-gray-900 ${isFullscreen ? 'fixed inset-0 z-50' : ''}`}
      style={containerStyle}
    >
      {/* Toolbar */}
      {showToolbar && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700 shrink-0">
          <div className="flex items-center gap-2">
            <DesktopOutlined className="text-gray-400" />
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ backgroundColor: status.color }}
            />
            <span className="text-xs text-gray-400">{status.text}</span>
          </div>

          <Space size="small">
            {/* Resolution selector */}
            {dynamicResize && (
              <Select
                size="small"
                value={currentResolution}
                onChange={handleResolutionChange}
                options={RESOLUTION_PRESETS}
                className="w-36"
                popupMatchSelectWidth={false}
                suffixIcon={<ExpandOutlined className="text-gray-400" />}
              />
            )}

            {/* Audio toggle */}
            <Tooltip title={isMuted ? 'Unmute audio' : 'Mute audio'}>
              <Button
                type="text"
                size="small"
                icon={isMuted ? <AudioMutedOutlined /> : <AudioOutlined />}
                onClick={() => { setIsMuted((prev) => !prev); }}
                className={`text-gray-400 hover:text-white ${!isMuted ? '!text-blue-400' : ''}`}
                aria-label={isMuted ? 'Unmute audio' : 'Mute audio'}
              />
            </Tooltip>

            {/* Reconnect */}
            <Tooltip title="Reconnect">
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                onClick={handleReconnect}
                disabled={connectionState === 'connecting'}
                className="text-gray-400 hover:text-white"
                aria-label="Reconnect"
              />
            </Tooltip>

            {/* Fullscreen */}
            <Tooltip title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
              <Button
                type="text"
                size="small"
                icon={isFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                onClick={toggleFullscreen}
                className="text-gray-400 hover:text-white"
                aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              />
            </Tooltip>
          </Space>
        </div>
      )}

      {/* VNC canvas container */}
      <div className="flex-1 relative bg-black overflow-hidden">
        {connectionState === 'connecting' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/50 z-10 pointer-events-none">
            <Spin indicator={<LoadingOutlined style={{ fontSize: 32 }} spin />} />
            <span className="text-white text-sm">Connecting to desktop...</span>
          </div>
        )}

        {(connectionState === 'error' || connectionState === 'disconnected') && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 z-10">
            <DisconnectOutlined className="text-4xl text-gray-500" />
            <span className="text-gray-400">
              {connectionState === 'error' ? 'Failed to connect to desktop' : 'Disconnected'}
            </span>
            <Button size="small" onClick={handleReconnect}>
              Reconnect
            </Button>
          </div>
        )}

        <div
          ref={canvasContainerRef}
          className="w-full h-full"
          style={{ touchAction: 'none', userSelect: 'none' }}
          onDragStart={(e) => { e.preventDefault(); }}
        />
      </div>
    </div>
  );
}

export default KasmVNCViewer;
