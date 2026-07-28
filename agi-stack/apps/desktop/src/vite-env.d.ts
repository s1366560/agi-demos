/// <reference types="vite/client" />

type DesktopInvoke = <T = string>(command: string, args?: Record<string, unknown>) => Promise<T>;

type WebControlPlaneDestination =
  | 'tenant-overview'
  | 'agent-workspace'
  | 'project-overview'
  | 'project-memories'
  | 'project-graph'
  | 'project-settings';

type WebControlPlaneRequest = {
  destination: WebControlPlaneDestination;
  tenantId: string;
  projectId: string;
};

type WebControlPlaneCapability = {
  availability: 'available' | 'unavailable';
  contractVersion: 1;
  reasonCode:
    | 'capability_snapshot_loading'
    | 'capability_snapshot_unavailable'
    | 'web_control_plane_configured'
    | 'web_control_plane_origin_invalid'
    | 'web_control_plane_origin_unconfigured';
  source: 'development_override' | 'none' | 'signed_build';
};

type DesktopNativeCapabilitySnapshot = {
  contractVersion: 1;
  webControlPlane: WebControlPlaneCapability;
};

type DesktopDisplayCapture = {
  dataUrl: string;
  displayId: string;
  height: number;
  mimeType: 'image/png';
  pngBytes: number;
  width: number;
};

interface Window {
  __MEMSTACK_DESKTOP__?: {
    runtime: 'electron';
    captureCurrentDisplay?: () => Promise<DesktopDisplayCapture>;
    getCapabilities?: () => Promise<DesktopNativeCapabilitySnapshot>;
    openWebControlPlane?: (request: WebControlPlaneRequest) => Promise<void>;
    core?: {
      invoke?: DesktopInvoke;
    };
    events?: {
      onSidecarRecovered?: (listener: () => void) => () => void;
    };
  };
}
