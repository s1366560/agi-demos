import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { DesktopRuntimeConfig } from '../../types';
import {
  createSandboxRuntimeClient,
  SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
  type SandboxRuntimeCapability,
  type SandboxRuntimeClient,
} from './sandboxRuntimeClient';
import {
  createSandboxRuntimeSurfaceClient,
  type RemoteDesktopResolution,
  type RemoteDesktopSession,
  type SandboxRuntimeCapabilitySnapshot,
} from './sandboxRuntimeSurfaceClient';

export type SandboxRuntimeLoadStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'unavailable';

export type RemoteDesktopLoadStatus =
  | 'idle'
  | 'starting'
  | 'ready'
  | 'unavailable'
  | 'error';

export type SessionSandboxRuntimeSurface = {
  capabilityStatus: SandboxRuntimeLoadStatus;
  capabilityLoadReason: string | null;
  capabilities: SandboxRuntimeCapabilitySnapshot | null;
  filesCapability: SandboxRuntimeCapability;
  remoteDesktopCapability: SandboxRuntimeCapability;
  runtimeClient: SandboxRuntimeClient | null;
  fileClient: SandboxRuntimeClient | null;
  remoteDesktopSession: RemoteDesktopSession | null;
  remoteDesktopRevision: number;
  remoteDesktopStatus: RemoteDesktopLoadStatus;
  remoteDesktopReason: string | null;
  remoteDesktopResolution: RemoteDesktopResolution;
  setRemoteDesktopResolution: (resolution: RemoteDesktopResolution) => void;
  reloadCapabilities: () => void;
  startRemoteDesktop: (resolution?: RemoteDesktopResolution) => Promise<void>;
};

const DEFAULT_REMOTE_DESKTOP_RESOLUTION: RemoteDesktopResolution = '1920x1080';

export function useSandboxRuntimeSurface(
  config: DesktopRuntimeConfig,
  enabled: boolean,
): SessionSandboxRuntimeSurface {
  const client = useMemo(
    () => createSandboxRuntimeSurfaceClient(config),
    [config],
  );
  const [capabilityStatus, setCapabilityStatus] =
    useState<SandboxRuntimeLoadStatus>('idle');
  const [capabilityLoadReason, setCapabilityLoadReason] = useState<string | null>(
    'sandbox_runtime_scope_unavailable',
  );
  const [capabilities, setCapabilities] =
    useState<SandboxRuntimeCapabilitySnapshot | null>(null);
  const [capabilityAttempt, setCapabilityAttempt] = useState(0);
  const [remoteDesktopSession, setRemoteDesktopSession] =
    useState<RemoteDesktopSession | null>(null);
  const [remoteDesktopRevision, setRemoteDesktopRevision] = useState(0);
  const [remoteDesktopStatus, setRemoteDesktopStatus] =
    useState<RemoteDesktopLoadStatus>('idle');
  const [remoteDesktopReason, setRemoteDesktopReason] = useState<string | null>(
    null,
  );
  const [remoteDesktopResolution, setRemoteDesktopResolution] =
    useState<RemoteDesktopResolution>(DEFAULT_REMOTE_DESKTOP_RESOLUTION);
  const remoteDesktopOperationRef = useRef(0);

  const reloadCapabilities = useCallback(() => {
    setCapabilityAttempt((current) => current + 1);
  }, []);

  useEffect(() => {
    remoteDesktopOperationRef.current += 1;
    setCapabilities(null);
    setRemoteDesktopSession(null);
    setRemoteDesktopRevision(0);
    setRemoteDesktopStatus('idle');
    setRemoteDesktopReason(null);
    if (!enabled) {
      setCapabilityStatus('idle');
      setCapabilityLoadReason('sandbox_runtime_scope_unavailable');
      return undefined;
    }

    const controller = new AbortController();
    setCapabilityStatus('loading');
    setCapabilityLoadReason(null);
    void client
      .loadCapabilities(controller.signal)
      .then((snapshot) => {
        if (controller.signal.aborted) return;
        setCapabilities(snapshot);
        setCapabilityStatus('ready');
        setCapabilityLoadReason(null);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setCapabilities(null);
        setCapabilityStatus('unavailable');
        setCapabilityLoadReason('sandbox_runtime_capability_request_failed');
      });
    return () => controller.abort();
  }, [capabilityAttempt, client, enabled]);

  const runtimeClient = useMemo(
    () => (capabilities ? createSandboxRuntimeClient(config, capabilities) : null),
    [capabilities, config],
  );

  const startRemoteDesktop = useCallback(
    async (resolution?: RemoteDesktopResolution) => {
      const operation = remoteDesktopOperationRef.current + 1;
      remoteDesktopOperationRef.current = operation;
      if (!capabilities) {
        setRemoteDesktopSession(null);
        setRemoteDesktopStatus('unavailable');
        setRemoteDesktopReason(
          capabilityLoadReason ?? 'sandbox_runtime_capability_contract_unavailable',
        );
        return;
      }

      setRemoteDesktopStatus('starting');
      setRemoteDesktopReason(null);
      try {
        const result = await client.openRemoteDesktop(capabilities, {
          resolution: resolution ?? remoteDesktopResolution,
        });
        if (remoteDesktopOperationRef.current !== operation) return;
        if (result.status === 'unavailable') {
          setRemoteDesktopSession(null);
          setRemoteDesktopStatus('unavailable');
          setRemoteDesktopReason(result.reason_code);
          return;
        }
        setRemoteDesktopSession(result.value);
        setRemoteDesktopRevision((current) => current + 1);
        setRemoteDesktopStatus('ready');
        setRemoteDesktopReason(null);
      } catch {
        if (remoteDesktopOperationRef.current !== operation) return;
        setRemoteDesktopSession(null);
        setRemoteDesktopStatus('error');
        setRemoteDesktopReason('kasm_remote_desktop_request_failed');
      }
    },
    [
      capabilities,
      capabilityLoadReason,
      client,
      remoteDesktopResolution,
    ],
  );

  return {
    capabilityStatus,
    capabilityLoadReason,
    capabilities,
    filesCapability:
      capabilities?.files ?? SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE.files,
    remoteDesktopCapability:
      capabilities?.kasm_vnc ?? SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE.kasm_vnc,
    runtimeClient,
    fileClient: runtimeClient,
    remoteDesktopSession,
    remoteDesktopRevision,
    remoteDesktopStatus,
    remoteDesktopReason,
    remoteDesktopResolution,
    setRemoteDesktopResolution,
    reloadCapabilities,
    startRemoteDesktop,
  };
}
