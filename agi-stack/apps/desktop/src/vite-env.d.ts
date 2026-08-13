/// <reference types="vite/client" />

type DesktopInvoke = <T = string>(command: string, args?: Record<string, unknown>) => Promise<T>;

type DesktopWorkspaceCoreHelperStatus = Readonly<{
  state: 'starting' | 'running' | 'restartScheduled' | 'failed' | 'stopped';
  pid: number | null;
  apiBaseUrl: string | null;
  restartAttempts: number;
  restartGeneration: number;
  failureReason: string | null;
  cutoverState: 'legacy-only' | 'importing' | 'core-authoritative' | 'core-unavailable';
}>;

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
  workspaceCore: Readonly<{
    state: DesktopWorkspaceCoreHelperStatus['state'];
    healthy: boolean;
    restartAttempts: number;
    restartGeneration: number;
    cutoverState: DesktopWorkspaceCoreHelperStatus['cutoverState'];
    terminalFailureReason: string | null;
  }>;
};

type DesktopDisplayCapture = {
  dataUrl: string;
  displayId: string;
  height: number;
  mimeType: 'image/png';
  pngBytes: number;
  width: number;
};

type DesktopFileOpenPurpose = 'attachment' | 'skill_package';

type DesktopFilePayload = Readonly<{
  filename: string;
  mimeType: string;
  bytes: Uint8Array;
}>;

type DesktopFileSaveRequest = Readonly<{
  suggestedName: string;
  mimeType: string;
  bytes: Uint8Array;
}>;

type DesktopFileSaveResult =
  | Readonly<{ status: 'cancelled' }>
  | Readonly<{ status: 'saved'; bytesWritten: number }>;

type DesktopFileOpenRequest = Readonly<{
  purpose: DesktopFileOpenPurpose;
}>;

type DesktopFileOpenResult =
  | Readonly<{ status: 'cancelled' }>
  | Readonly<{
      status: 'selected';
      files: readonly DesktopFilePayload[];
    }>;

type DesktopFileIngestRequest = Readonly<{
  purpose: 'attachment';
  files: readonly DesktopFilePayload[];
}>;

type DesktopFileIngestResult = Readonly<{
  status: 'ingested';
  files: readonly DesktopFilePayload[];
}>;

type DesktopIabTabSnapshot = Readonly<{
  tabId: number;
  windowId: number;
  title: string;
  url: string;
  active: boolean;
}>;

type DesktopIabTabsPayload = Readonly<{
  tabs: readonly DesktopIabTabSnapshot[];
  activeTabId: number | null;
}>;

type DesktopIabPaneBounds = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
}>;

type DesktopUpdateLifecycleState = Readonly<{
  schemaVersion: 2;
  phase:
    | 'disabled'
    | 'idle'
    | 'checking'
    | 'available'
    | 'not_available'
    | 'downloading'
    | 'downloaded'
    | 'applying'
    | 'verifying'
    | 'recovered'
    | 'failed';
  currentVersion: string;
  candidateVersion: string | null;
  recoveryVersion: string | null;
  progress: number | null;
  reasonCode: string | null;
  retryable: boolean;
  allowedActions: readonly ('check' | 'restart_to_apply')[];
}>;

interface Window {
  __MEMSTACK_DESKTOP__?: {
    runtime: 'electron';
    platform?: string;
    captureCurrentDisplay?: () => Promise<DesktopDisplayCapture>;
    getCapabilities?: () => Promise<DesktopNativeCapabilitySnapshot>;
    openWebControlPlane?: (request: WebControlPlaneRequest) => Promise<void>;
    focusMainWindow?: () => Promise<void>;
    windowControls?: Readonly<{
      minimize(): Promise<void>;
      maximize(): Promise<void>;
      unmaximize(): Promise<void>;
      toggleMaximize(): Promise<void>;
      isMaximized(): Promise<boolean>;
      close(): Promise<void>;
    }>;
    files?: Readonly<{
      save(request: DesktopFileSaveRequest): Promise<DesktopFileSaveResult>;
      open(request: DesktopFileOpenRequest): Promise<DesktopFileOpenResult>;
      ingest(request: DesktopFileIngestRequest): Promise<DesktopFileIngestResult>;
    }>;
    updates?: Readonly<{
      getState(): Promise<DesktopUpdateLifecycleState>;
      check(): Promise<DesktopUpdateLifecycleState>;
      restartToApply(): Promise<DesktopUpdateLifecycleState>;
      subscribe(listener: (state: DesktopUpdateLifecycleState) => void): () => void;
      /** @deprecated Use subscribe. */
      onStateChanged(listener: (state: DesktopUpdateLifecycleState) => void): () => void;
    }>;
    iab?: Readonly<{
      status(): Promise<{ status: string }>;
      listTabs(): Promise<DesktopIabTabsPayload>;
      createTab(url?: string): Promise<{ tabId: number }>;
      closeTab(tabId: number): Promise<void>;
      focusTab(tabId: number): Promise<void>;
      showPane(bounds: DesktopIabPaneBounds): Promise<void>;
      setBounds(bounds: DesktopIabPaneBounds): Promise<void>;
      hidePane(): Promise<void>;
      onTabsChanged(listener: (payload: DesktopIabTabsPayload) => void): () => void;
    }>;
    core?: {
      invoke?: DesktopInvoke;
    };
    events?: {
      onSidecarRecovered?: (listener: () => void) => () => void;
      onOAuthSessionChanged?: (listener: (payload: unknown) => void) => () => void;
    };
  };
}
