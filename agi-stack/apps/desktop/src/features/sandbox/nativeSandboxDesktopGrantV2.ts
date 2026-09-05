import type { DesktopRuntimeConfig } from '../../types';
import type { KasmProxySession } from './sandboxRuntimeClient';

export type NativeSandboxDesktopGrantV2 = Readonly<{
  grantId: string;
  frameName: string;
  frameUrl: string;
  release(): Promise<void>;
}>;

/** Native grants never fall back to a renderer URL or cookie transport. */
export async function openNativeSandboxDesktopGrantV2(
  config: DesktopRuntimeConfig,
  descriptor: KasmProxySession,
  signal?: AbortSignal,
): Promise<NativeSandboxDesktopGrantV2 | null> {
  if (
    config.mode !== 'cloud' ||
    typeof window === 'undefined' ||
    window.__MEMSTACK_DESKTOP__?.runtime !== 'electron'
  )
    return null;
  const bridge = window.__MEMSTACK_DESKTOP__;
  if (!bridge.core?.invoke) throw new Error('sandbox_desktop_grant_bridge_unavailable');
  signal?.throwIfAborted();
  const invoke = bridge.core.invoke.bind(bridge.core);
  const requestId = crypto.randomUUID();
  const expectedUrl = new URL(descriptor.proxy_url, new URL(config.apiBaseUrl).origin).toString();
  let grantId: string | undefined;
  let closePending: Promise<void> | null = null;
  let closeGranted: Promise<void> | null = null;
  const close = (): Promise<void> => {
    if (grantId) {
      closeGranted ??= Promise.resolve().then(async () => {
        await invoke('sandbox_desktop_grant_close', { requestId, grantId });
      });
      return closeGranted;
    }
    closePending ??= Promise.resolve().then(async () => {
      await invoke('sandbox_desktop_grant_close', { requestId });
    });
    return closePending;
  };
  const onAbort = () => {
    void close().catch(() => undefined);
  };
  signal?.addEventListener('abort', onAbort, { once: true });
  try {
    signal?.throwIfAborted();
    const raw: unknown = await invoke('sandbox_desktop_grant_open', {
      requestId,
      tenantId: config.tenantId,
      projectId: config.projectId,
      descriptor,
    });
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw))
      throw new Error('sandbox_desktop_grant_response_invalid');
    const value = raw as Record<string, unknown>;
    if (opaqueId(value.grantId)) grantId = value.grantId;
    if (
      Object.keys(value).length !== 3 ||
      !grantId ||
      !opaqueId(value.frameName) ||
      value.frameUrl !== expectedUrl
    )
      throw new Error('sandbox_desktop_grant_response_invalid');
    signal?.throwIfAborted();
    let releasePromise: Promise<void> | null = null;
    return Object.freeze({
      grantId,
      frameName: value.frameName,
      frameUrl: expectedUrl,
      release() {
        signal?.removeEventListener('abort', onAbort);
        releasePromise ??= close();
        return releasePromise;
      },
    });
  } catch (error) {
    signal?.removeEventListener('abort', onAbort);
    // requestId closes an in-flight open; a late known grant is closed as well.
    // Preserve the operation failure even if native cleanup also rejects.
    await close().catch(() => undefined);
    throw error;
  }
}

function opaqueId(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= 512 &&
    value.trim() === value &&
    !/[\u0000-\u0020\u007f]/u.test(value)
  );
}
