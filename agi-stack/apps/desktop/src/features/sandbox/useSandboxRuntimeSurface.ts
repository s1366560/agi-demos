import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';

import type { DesktopProjectSandboxSurfaceClientV2 } from '../../plugins/desktopProjectSandboxSurfaceAuthorityModuleV2';
import type { DesktopRuntimeConfig } from '../../types';
import {
  SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
  type SandboxRuntimeCapability,
  type SandboxRuntimeFileClient,
} from './sandboxRuntimeClient';
import {
  type RemoteDesktopResolution,
  type RemoteDesktopSession,
  type SandboxRuntimeCapabilitySnapshot,
} from './sandboxRuntimeSurfaceClient';

export type SandboxRuntimeLoadStatus = 'idle' | 'loading' | 'ready' | 'unavailable';

export type RemoteDesktopLoadStatus = 'idle' | 'starting' | 'ready' | 'unavailable' | 'error';

export type SessionSandboxRuntimeSurface = {
  capabilityStatus: SandboxRuntimeLoadStatus;
  capabilityLoadReason: string | null;
  capabilities: SandboxRuntimeCapabilitySnapshot | null;
  filesCapability: SandboxRuntimeCapability;
  remoteDesktopCapability: SandboxRuntimeCapability;
  runtimeClient: SandboxRuntimeFileClient | null;
  fileClient: SandboxRuntimeFileClient | null;
  fileRootPath: string;
  remoteDesktopSession: RemoteDesktopSession | null;
  remoteDesktopRevision: number;
  remoteDesktopStatus: RemoteDesktopLoadStatus;
  remoteDesktopReason: string | null;
  remoteDesktopResolution: RemoteDesktopResolution;
  setRemoteDesktopResolution: (resolution: RemoteDesktopResolution) => void;
  reloadCapabilities: () => void;
  startRemoteDesktop: (resolution?: RemoteDesktopResolution) => Promise<void>;
  stopRemoteDesktop: () => Promise<void>;
};

const DEFAULT_REMOTE_DESKTOP_RESOLUTION: RemoteDesktopResolution = '1920x1080';

export function useSandboxRuntimeSurface(
  config: DesktopRuntimeConfig,
  enabled: boolean,
  client: DesktopProjectSandboxSurfaceClientV2,
): SessionSandboxRuntimeSurface {
  const context = useMemo(() => ({ config, client, enabled }), [config, client, enabled]);
  const contextRef = useRef(context);
  contextRef.current = context;
  const lifetimeRef = useRef<{
    context: typeof context;
    controller: AbortController;
    remoteController: AbortController | null;
    session: (RemoteDesktopSession & { release(): Promise<void> }) | null;
  } | null>(null);
  const [capabilityStatus, setCapabilityStatus] = useState<SandboxRuntimeLoadStatus>('idle');
  const [capabilityLoadReason, setCapabilityLoadReason] = useState<string | null>(
    'sandbox_runtime_scope_unavailable',
  );
  const [capabilities, setCapabilities] = useState<SandboxRuntimeCapabilitySnapshot | null>(null);
  const [capabilityAttempt, setCapabilityAttempt] = useState(0);
  const [remoteDesktopSession, setRemoteDesktopSession] = useState<RemoteDesktopSession | null>(
    null,
  );
  const [remoteDesktopRevision, setRemoteDesktopRevision] = useState(0);
  const [remoteDesktopStatus, setRemoteDesktopStatus] = useState<RemoteDesktopLoadStatus>('idle');
  const [remoteDesktopReason, setRemoteDesktopReason] = useState<string | null>(null);
  const [remoteDesktopResolution, setRemoteDesktopResolution] = useState<RemoteDesktopResolution>(
    DEFAULT_REMOTE_DESKTOP_RESOLUTION,
  );
  const remoteDesktopOperationRef = useRef(0);
  const capabilityLifetimeRef = useRef<typeof lifetimeRef.current>(null);

  const reloadCapabilities = useCallback(() => {
    setCapabilityAttempt((current) => current + 1);
  }, []);

  useLayoutEffect(() => {
    const lifetime = {
      context,
      controller: new AbortController(),
      remoteController: null as AbortController | null,
      session: null as (RemoteDesktopSession & { release(): Promise<void> }) | null,
    };
    lifetimeRef.current = lifetime;
    const current = () => !lifetime.controller.signal.aborted && contextRef.current === context;
    remoteDesktopOperationRef.current += 1;
    setCapabilities(null);
    setRemoteDesktopSession(null);
    setRemoteDesktopRevision(0);
    setRemoteDesktopStatus('idle');
    setRemoteDesktopReason(null);
    if (!enabled) {
      setCapabilityStatus('idle');
      setCapabilityLoadReason('sandbox_runtime_scope_unavailable');
    } else {
      setCapabilityStatus('loading');
      setCapabilityLoadReason(null);
      void client
        .loadCapabilities(lifetime.controller.signal)
        .then((snapshot) => {
          if (!current()) return;
          capabilityLifetimeRef.current = lifetime;
          setCapabilities(snapshot);
          setCapabilityStatus('ready');
          setCapabilityLoadReason(null);
        })
        .catch(() => {
          if (!current()) return;
          setCapabilityStatus('unavailable');
          setCapabilityLoadReason('sandbox_runtime_capability_request_failed');
        });
    }
    return () => {
      lifetime.controller.abort();
      lifetime.remoteController?.abort();
      const session = lifetime.session;
      lifetime.session = null;
      if (session)
        void session.release().catch(() => {
          // Cleanup cannot publish UI state after its context has been released.
          console.warn('sandbox_remote_desktop_lease_release_failed');
        });
    };
  }, [capabilityAttempt, context, client, enabled]);

  const runtimeClient = useMemo<SandboxRuntimeFileClient | null>(() => {
    if (!capabilities) return null;
    const lifetime = lifetimeRef.current;
    const execute = async <T>(
      operation: (signal: AbortSignal) => Promise<T>,
      signal?: AbortSignal,
    ): Promise<T> => {
      const controller = new AbortController();
      const abort = () => controller.abort();
      const current = () =>
        lifetime &&
        lifetimeRef.current === lifetime &&
        lifetime.context === context &&
        capabilityLifetimeRef.current === lifetime &&
        contextRef.current === context &&
        !lifetime.controller.signal.aborted &&
        !signal?.aborted;
      if (!current()) throw new DOMException('Sandbox context released', 'AbortError');
      lifetime!.controller.signal.addEventListener('abort', abort, { once: true });
      signal?.addEventListener('abort', abort, { once: true });
      try {
        const result = await operation(controller.signal);
        if (!current()) throw new DOMException('Sandbox context released', 'AbortError');
        return result;
      } finally {
        lifetime!.controller.signal.removeEventListener('abort', abort);
        signal?.removeEventListener('abort', abort);
      }
    };
    return {
      listFiles: (request, signal) =>
        execute((linked) => client.listFiles(capabilities, request, linked), signal),
      readFile: (request, signal) =>
        execute((linked) => client.readFile(capabilities, request, linked), signal),
      downloadFile: (request, signal) =>
        execute((linked) => client.downloadFile(capabilities, request, linked), signal),
    };
  }, [capabilities, client, context]);

  const stopRemoteDesktop = useCallback(async () => {
    const lifetime = lifetimeRef.current;
    if (
      !lifetime ||
      lifetime.context !== context ||
      contextRef.current !== context ||
      lifetime.controller.signal.aborted
    )
      return;
    const operation = ++remoteDesktopOperationRef.current;
    lifetime.remoteController?.abort();
    lifetime.remoteController = null;
    const session = lifetime.session;
    lifetime.session = null;
    setRemoteDesktopSession(null);
    setRemoteDesktopStatus('idle');
    setRemoteDesktopReason(null);
    try {
      if (session) await session.release();
    } catch {
      if (
        lifetime.controller.signal.aborted ||
        contextRef.current !== context ||
        remoteDesktopOperationRef.current !== operation
      )
        return;
      setRemoteDesktopStatus('error');
      setRemoteDesktopReason('sandbox_remote_desktop_lease_release_failed');
    }
  }, [context]);

  const startRemoteDesktop = useCallback(
    async (resolution?: RemoteDesktopResolution) => {
      const lifetime = lifetimeRef.current;
      if (
        !lifetime ||
        lifetime.context !== context ||
        contextRef.current !== context ||
        lifetime.controller.signal.aborted ||
        !enabled
      )
        return;
      const operation = ++remoteDesktopOperationRef.current;
      lifetime.remoteController?.abort();
      const controller = new AbortController();
      lifetime.remoteController = controller;
      const current = () =>
        !controller.signal.aborted &&
        !lifetime.controller.signal.aborted &&
        contextRef.current === context &&
        remoteDesktopOperationRef.current === operation;
      const previous = lifetime.session;
      lifetime.session = null;
      setRemoteDesktopSession(null);
      let releasing = Boolean(previous);
      setRemoteDesktopStatus('starting');
      setRemoteDesktopReason(null);
      try {
        if (previous) await previous.release();
        releasing = false;
        if (!current()) return;
        if (!capabilities || capabilityLifetimeRef.current !== lifetime) {
          setRemoteDesktopStatus('unavailable');
          setRemoteDesktopReason(
            capabilityLoadReason ?? 'sandbox_runtime_capability_contract_unavailable',
          );
          return;
        }

        const result = await client.openRemoteDesktop(
          capabilities,
          {
            resolution: resolution ?? remoteDesktopResolution,
          },
          controller.signal,
        );
        if (!current()) {
          if (result.status === 'ready') await result.value.release();
          return;
        }
        if (result.status === 'unavailable') {
          setRemoteDesktopSession(null);
          setRemoteDesktopStatus('unavailable');
          setRemoteDesktopReason(result.reason_code);
          return;
        }
        lifetime.session = result.value;
        setRemoteDesktopSession(result.value);
        setRemoteDesktopRevision((current) => current + 1);
        setRemoteDesktopStatus('ready');
        setRemoteDesktopReason(null);
      } catch {
        if (!current()) return;
        setRemoteDesktopSession(null);
        setRemoteDesktopStatus('error');
        setRemoteDesktopReason(
          releasing
            ? 'sandbox_remote_desktop_lease_release_failed'
            : 'kasm_remote_desktop_request_failed',
        );
      }
    },
    [capabilities, context, enabled, capabilityLoadReason, client, remoteDesktopResolution],
  );

  return {
    capabilityStatus,
    capabilityLoadReason,
    capabilities,
    filesCapability: capabilities?.files ?? SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE.files,
    remoteDesktopCapability:
      capabilities?.kasm_vnc ?? SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE.kasm_vnc,
    runtimeClient,
    fileClient: runtimeClient,
    fileRootPath: config.mode === 'local' ? '/workspace' : '/',
    remoteDesktopSession,
    remoteDesktopRevision,
    remoteDesktopStatus,
    remoteDesktopReason,
    remoteDesktopResolution,
    setRemoteDesktopResolution,
    reloadCapabilities,
    startRemoteDesktop,
    stopRemoteDesktop,
  };
}
