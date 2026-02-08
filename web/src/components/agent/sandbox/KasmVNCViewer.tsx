/**
 * KasmVNCViewer - Embedded KasmVNC web client for sandbox desktop access
 *
 * Embeds KasmVNC's built-in web client via iframe, providing:
 * - WebP encoding with dynamic quality adjustment
 * - Bi-directional clipboard (text + images)
 * - File transfer (drag-drop upload/download)
 * - Audio streaming via PulseAudio
 * - Dynamic resolution resize
 * - WebRTC transport option for lower latency
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

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

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'error';

const RESOLUTION_PRESETS = [
  { label: '1280x720 (HD)', value: '1280x720' },
  { label: '1600x900', value: '1600x900' },
  { label: '1920x1080 (FHD)', value: '1920x1080' },
  { label: '2560x1440 (QHD)', value: '2560x1440' },
];

export interface KasmVNCViewerProps {
  /** URL to the KasmVNC web client (proxied through API) */
  proxyUrl: string;
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
  proxyUrl,
  resolution = '1920x1080',
  audioEnabled = false,
  dynamicResize = true,
  onConnect,
  onError,
  onResolutionChange,
  showToolbar = true,
}: KasmVNCViewerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isMuted, setIsMuted] = useState(!audioEnabled);
  const [currentResolution, setCurrentResolution] = useState(resolution);

  // Build the KasmVNC client URL with auto-connect parameters
  const iframeUrl = useMemo(() => {
    const url = new URL(proxyUrl, window.location.origin);
    // KasmVNC auto-connect parameters
    url.searchParams.set('autoconnect', '1');
    url.searchParams.set('resize', dynamicResize ? 'remote' : 'scale');

    // Override WebSocket path so KasmVNC connects through our API proxy
    // KasmVNC builds WS URL as: {wss|ws}://{host}:{port}/{path}
    // We need it to hit our WebSocket proxy endpoint
    const proxyBase = proxyUrl.split('?')[0].replace(/\/$/, '');
    const token = url.searchParams.get('token');
    let wsPath = `${proxyBase}/websockify`;
    if (token) {
      wsPath += `?token=${encodeURIComponent(token)}`;
    }
    // Remove leading slash — KasmVNC prepends "/"
    url.searchParams.set('path', wsPath.replace(/^\//, ''));

    return url.toString();
  }, [proxyUrl, dynamicResize]);

  const handleIframeLoad = useCallback(() => {
    setConnectionState('connected');
    onConnect?.();
  }, [onConnect]);

  const handleIframeError = useCallback(() => {
    setConnectionState('error');
    onError?.('Failed to load KasmVNC web client');
  }, [onError]);

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
      // Fallback: toggle CSS-based fullscreen
      setIsFullscreen((prev) => !prev);
    }
  }, []);

  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  // Handle resolution change
  const handleResolutionChange = useCallback(
    (value: string) => {
      setCurrentResolution(value);
      onResolutionChange?.(value);
    },
    [onResolutionChange],
  );

  // Reload iframe
  const handleReload = useCallback(() => {
    if (iframeRef.current) {
      setConnectionState('connecting');
      iframeRef.current.src = iframeUrl;
    }
  }, [iframeUrl]);

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
                onClick={() => setIsMuted((prev) => !prev)}
                className={`text-gray-400 hover:text-white ${!isMuted ? '!text-blue-400' : ''}`}
                aria-label={isMuted ? 'Unmute audio' : 'Mute audio'}
              />
            </Tooltip>

            {/* Reload */}
            <Tooltip title="Reconnect">
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                onClick={handleReload}
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

      {/* KasmVNC iframe container */}
      <div className="flex-1 relative bg-black overflow-hidden">
        {connectionState === 'connecting' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/50 z-10">
            <Spin indicator={<LoadingOutlined style={{ fontSize: 32 }} spin />} />
            <span className="text-white text-sm">Connecting to desktop...</span>
          </div>
        )}

        {connectionState === 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 z-10">
            <DisconnectOutlined className="text-4xl text-gray-500" />
            <span className="text-gray-400">Failed to connect to desktop</span>
            <Button size="small" onClick={handleReload}>
              Retry
            </Button>
          </div>
        )}

        <iframe
          ref={iframeRef}
          src={iframeUrl}
          title="Remote Desktop (KasmVNC)"
          className="w-full h-full border-0"
          allow="clipboard-read; clipboard-write; autoplay"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          onLoad={handleIframeLoad}
          onError={handleIframeError}
          style={{ display: connectionState === 'error' ? 'none' : 'block' }}
        />
      </div>
    </div>
  );
}

export default KasmVNCViewer;
