/**
 * RemoteDesktopViewer - KasmVNC client viewer for sandbox desktop access
 *
 * Embeds KasmVNC web client with dynamic resolution, clipboard sync,
 * file transfer, and audio streaming support.
 */

import { DesktopOutlined } from '@ant-design/icons';

import type { DesktopStatus } from '../../../types/agent';
import { getAuthToken } from '../../../utils/tokenResolver';

import { KasmVNCViewer } from './KasmVNCViewer';

export interface RemoteDesktopViewerProps {
  /** Sandbox container ID */
  sandboxId: string;
  /** Project ID for proxy URL construction */
  projectId?: string;
  /** Desktop status information */
  desktopStatus: DesktopStatus | null;
  /** Called when viewer is ready */
  onReady?: () => void;
  /** Called when viewer encounters an error */
  onError?: (error: string) => void;
  /** Called when close button is clicked */
  onClose?: () => void;
  /** Called to change resolution */
  onResolutionChange?: (resolution: string) => void;
  /** Height of the viewer (default: "100%") */
  height?: string | number;
  /** Show toolbar (default: true) */
  showToolbar?: boolean;
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

  // Build proxy URL for KasmVNC web client with auth token
  const token = getAuthToken();
  const proxyUrl = `/api/v1/projects/${projectId}/sandbox/desktop/proxy/${token ? `?token=${encodeURIComponent(token)}` : ''}`;

  return (
    <KasmVNCViewer
      proxyUrl={proxyUrl}
      resolution={desktopStatus?.resolution}
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
