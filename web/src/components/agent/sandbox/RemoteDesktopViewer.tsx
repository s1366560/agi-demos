/**
 * RemoteDesktopViewer - noVNC client viewer for sandbox desktop access
 *
 * Displays a remote desktop session using noVNC web client
 * embedded in an iframe.
 */

import { useState, useCallback, useEffect, useRef } from 'react';

import {
  DesktopOutlined,
  ReloadOutlined,
  ExpandOutlined,
  CompressOutlined,
  CloseOutlined,
} from '@ant-design/icons';
import { Button, Spin, Alert, Space, Tooltip, Badge } from 'antd';

import type { DesktopStatus } from '../../../types/agent';

export interface RemoteDesktopViewerProps {
  /** Sandbox container ID */
  sandboxId: string;
  /** Desktop status information */
  desktopStatus: DesktopStatus | null;
  /** Called when viewer is ready */
  onReady?: () => void;
  /** Called when viewer encounters an error */
  onError?: (error: string) => void;
  /** Called when close button is clicked */
  onClose?: () => void;
  /** Height of the viewer (default: "100%") */
  height?: string | number;
  /** Show toolbar (default: true) */
  showToolbar?: boolean;
}

type ViewerStatus = 'loading' | 'ready' | 'error';

export function RemoteDesktopViewer({
  sandboxId,
  desktopStatus,
  onReady,
  onError,
  onClose,
  height = '100%',
  showToolbar = true,
}: RemoteDesktopViewerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Determine desktop URL from status
  const desktopUrl = desktopStatus?.url ?? null;

  // Track previous URL to detect changes
  const prevDesktopUrlRef = useRef<string | null>(null);

  // Initialize state based on desktopUrl
  const [viewerStatus, setViewerStatus] = useState<ViewerStatus>('loading');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [iframeKey, setIframeKey] = useState(0);

  // When desktopUrl changes, reset state in next tick
  useEffect(() => {
    if (prevDesktopUrlRef.current !== desktopUrl) {
      prevDesktopUrlRef.current = desktopUrl;
      // Use setTimeout to defer setState and avoid synchronous setState in effect
      setTimeout(() => {
        setIframeKey((prev) => prev + 1);
        setErrorMessage(null);
        setViewerStatus('loading');
      }, 0);
    }
  }, [desktopUrl]);

  // Handle iframe load event
  const handleIframeLoad = useCallback(() => {
    if (desktopUrl) {
      setViewerStatus('ready');
      onReady?.();
    }
  }, [desktopUrl, onReady]);

  // Handle iframe error event
  const handleIframeError = useCallback(() => {
    const error = 'Failed to load desktop viewer';
    setErrorMessage(error);
    setViewerStatus('error');
    onError?.(error);
  }, [onError]);

  // Refresh desktop
  const handleRefresh = useCallback(() => {
    setIframeKey((prev) => prev + 1);
    setViewerStatus('loading');
    setErrorMessage(null);
  }, []);

  // Toggle fullscreen
  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((prev) => !prev);
  }, []);

  // Status text
  const statusText = {
    loading: 'Connecting...',
    ready: 'Desktop Ready',
    error: errorMessage || 'Connection Error',
  };

  // Container style
  const containerStyle: React.CSSProperties = {
    height: isFullscreen ? '100vh' : height,
    position: isFullscreen ? 'fixed' : 'relative',
    top: isFullscreen ? 0 : 'auto',
    left: isFullscreen ? 0 : 'auto',
    width: isFullscreen ? '100vw' : '100%',
    zIndex: isFullscreen ? 50 : 'auto',
  };

  return (
    <div
      className={`flex flex-col bg-gray-900 ${isFullscreen ? 'fixed inset-0 z-50' : ''}`}
      style={containerStyle}
    >
      {/* Toolbar */}
      {showToolbar && (
        <div className="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <DesktopOutlined className="text-gray-400" />
            <span className="text-sm text-gray-300">Remote Desktop</span>
            <span className="text-xs text-gray-500">({sandboxId.slice(0, 8)})</span>
            <Badge
              status={
                viewerStatus === 'ready'
                  ? 'success'
                  : viewerStatus === 'error'
                    ? 'error'
                    : 'processing'
              }
              text={statusText[viewerStatus]}
              className="ml-2"
            />
          </div>

          <Space size="small">
            {desktopStatus?.running && (
              <Tooltip title="Refresh desktop">
                <Button
                  type="text"
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={handleRefresh}
                  className="text-gray-400 hover:text-white"
                  aria-label="Refresh desktop"
                />
              </Tooltip>
            )}
            <Tooltip title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}>
              <Button
                type="text"
                size="small"
                icon={isFullscreen ? <CompressOutlined /> : <ExpandOutlined />}
                onClick={toggleFullscreen}
                className="text-gray-400 hover:text-white"
                aria-label={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
              />
            </Tooltip>
            {onClose && (
              <Tooltip title="Close">
                <Button
                  type="text"
                  size="small"
                  icon={<CloseOutlined />}
                  onClick={onClose}
                  className="text-gray-400 hover:text-red-400"
                  aria-label="Close desktop viewer"
                />
              </Tooltip>
            )}
          </Space>
        </div>
      )}

      {/* Desktop Viewer */}
      <div className="flex-1 relative bg-black">
        {!desktopUrl ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center text-gray-500">
              <DesktopOutlined className="text-4xl mb-2" />
              <p>Desktop is not running</p>
              <p className="text-sm">Start the desktop to connect</p>
            </div>
          </div>
        ) : (
          <>
            {viewerStatus === 'loading' && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/50 z-10">
                <Spin size="large" />
                <span className="text-white">Connecting to desktop...</span>
              </div>
            )}

            {viewerStatus === 'error' && (
              <div className="absolute inset-0 flex items-center justify-center z-10">
                <Alert
                  type="error"
                  message={errorMessage || 'Failed to load desktop'}
                  showIcon
                  action={
                    <Button size="small" onClick={handleRefresh}>
                      Retry
                    </Button>
                  }
                  className="m-4"
                />
              </div>
            )}

            <iframe
              ref={iframeRef}
              key={iframeKey}
              src={desktopUrl}
              className="w-full h-full border-0"
              onLoad={handleIframeLoad}
              onError={handleIframeError}
              title="Remote Desktop"
              allowFullScreen
            />
          </>
        )}
      </div>
    </div>
  );
}

export default RemoteDesktopViewer;
