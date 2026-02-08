/**
 * RemoteDesktopViewer - noVNC client viewer for sandbox desktop access
 *
 * Uses @novnc/novnc RFB class for direct WebSocket VNC connection
 * with clipboard sync and keyboard handling.
 */

import { DesktopOutlined } from '@ant-design/icons';

import type { DesktopStatus } from '../../../types/agent';

import { NoVNCViewer } from './NoVNCViewer';

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

export function RemoteDesktopViewer({
  desktopStatus,
  onReady,
  onError,
  showToolbar = true,
}: RemoteDesktopViewerProps) {
  const wsUrl = desktopStatus?.wsUrl ?? null;
  const isRunning = desktopStatus?.running ?? false;

  if (!isRunning || !wsUrl) {
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

  return (
    <NoVNCViewer
      wsUrl={wsUrl}
      onConnect={onReady}
      onError={onError}
      showToolbar={showToolbar}
      showClipboard={false}
      scaleViewport={true}
    />
  );
}

export default RemoteDesktopViewer;
