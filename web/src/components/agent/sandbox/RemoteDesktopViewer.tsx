/**
 * RemoteDesktopViewer - KasmVNC client viewer for sandbox desktop access
 *
 * Connects to KasmVNC via direct noVNC RFB WebSocket connection through
 * the API proxy, with auto-resize and clipboard support.
 */

import { DesktopOutlined } from '@ant-design/icons';

import { getAuthToken } from '../../../utils/tokenResolver';

import { KasmVNCViewer } from './KasmVNCViewer';

import type { DesktopStatus } from '../../../types/agent';

export interface RemoteDesktopViewerProps {
  /** Sandbox container ID */
  sandboxId: string;
  /** Project ID for proxy URL construction */
  projectId?: string | undefined;
  /** Desktop status information */
  desktopStatus: DesktopStatus | null;
  /** Called when viewer is ready */
  onReady?: (() => void) | undefined;
  /** Called when viewer encounters an error */
  onError?: ((error: string) => void) | undefined;
  /** Called when close button is clicked */
  onClose?: (() => void) | undefined;
  /** Called to change resolution */
  onResolutionChange?: ((resolution: string) => void) | undefined;
  /** Height of the viewer (default: "100%") */
  height?: string | number | undefined;
  /** Show toolbar (default: true) */
  showToolbar?: boolean | undefined;
}

export function RemoteDesktopViewer({
  projectId,
  desktopStatus,
  onReady,
  onError,
  onResolutionChange,
  showToolbar = true,
}: RemoteDesktopViewerProps) {
  const isRunning = desktopStatus?.running ?? false;

  if (!isRunning || !projectId) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-900">
        <div className="text-center text-gray-500">
          <DesktopOutlined className="text-4xl mb-2" />
          <p>Desktop is not running</p>
          <p className="text-sm">Start the desktop to connect</p>
        </div>
      </div>
    );
  }

  // Build WebSocket URL for direct RFB connection through the API proxy
  const token = getAuthToken();
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl =
    `${wsProtocol}//${window.location.host}` +
    `/api/v1/projects/${projectId}/sandbox/desktop/proxy/websockify` +
    (token ? `?token=${encodeURIComponent(token)}` : '');

  return (
    <KasmVNCViewer
      wsUrl={wsUrl}
      resolution="auto"
      audioEnabled={desktopStatus?.audioEnabled}
      dynamicResize={desktopStatus?.dynamicResize}
      onConnect={onReady}
      onError={onError}
      onResolutionChange={onResolutionChange}
      showToolbar={showToolbar}
    />
  );
}

export default RemoteDesktopViewer;
