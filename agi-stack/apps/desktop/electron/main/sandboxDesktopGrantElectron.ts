import type { Session, WebContents, WebFrameMain } from 'electron';
import {
  SandboxDesktopGrantRegistry,
  type SandboxDesktopGrantNetworkDetails,
} from './sandboxDesktopGrantRegistry';

type ResolveOwner = (ownerId: number) => WebContents | undefined;
const installations = new WeakMap<
  Session,
  { registry: SandboxDesktopGrantRegistry; dispose(): void }
>();

/** One listener per Electron Session; all grant decisions remain in the registry. */
export function installSandboxDesktopGrantElectron(
  session: Session,
  registry: SandboxDesktopGrantRegistry,
  options: Readonly<{ resolveOwner: ResolveOwner }>,
): Readonly<{ dispose(): void }> {
  const existing = installations.get(session);
  if (existing) {
    if (existing.registry !== registry)
      throw new Error('sandbox_desktop_grant_session_already_installed');
    return existing;
  }
  const watched = new Map<
    number,
    {
      contents: WebContents;
      navigation: (details: { url: string; frame: WebFrameMain | null }) => void;
      destroyed: () => void;
    }
  >();
  const observedFrames = new Map<number, Set<number>>();
  const frameSweep = setInterval(() => {
    for (const [ownerId, frames] of observedFrames) {
      try {
        const owner = options.resolveOwner(ownerId);
        const alive = owner && !owner.isDestroyed() ? owner.mainFrame.framesInSubtree : [];
        for (const id of frames) {
          const frame = alive.find((candidate) => candidate.frameTreeNodeId === id);
          if (!frame) {
            registry.observeFrameDestroyed(ownerId, id);
            frames.delete(id);
          } else if (frame.url) registry.observeFrameNavigation(ownerId, id, frame.url);
        }
        if (!frames.size) observedFrames.delete(ownerId);
      } catch {
        void registry.revokeOwner(ownerId).catch(() => undefined);
      }
    }
  }, 100);
  function watch(ownerId: number | undefined): void {
    if (ownerId === undefined || watched.has(ownerId)) return;
    const contents = options.resolveOwner(ownerId);
    if (!contents || contents.isDestroyed() || contents.session !== session) return;
    const navigation = (details: { url: string; frame: WebFrameMain | null }) => {
      if (!details.frame) return;
      try {
        registry.observeFrameNavigation(ownerId, details.frame.frameTreeNodeId, details.url);
      } catch {
        /* disposed frame */
      }
    };
    const destroyed = () => {
      void registry.revokeOwner(ownerId).catch(() => undefined);
      watched.delete(ownerId);
    };
    contents.on('did-start-navigation', navigation);
    contents.on('will-frame-navigate', navigation);
    contents.once('destroyed', destroyed);
    watched.set(ownerId, { contents, navigation, destroyed });
  }
  // All URLs are observed so a bound frame leaving its prefix revokes before it can
  // fetch the old authorized origin again. No headers change for unrelated traffic.
  session.webRequest.onBeforeSendHeaders((details, callback) => {
    watch(details.webContentsId);
    const snapshot = networkDetails(details);
    if (details.frame && details.resourceType !== 'subFrame') {
      try {
        if (details.frame.url)
          registry.observeFrameNavigation(
            details.webContentsId ?? -1,
            details.frame.frameTreeNodeId,
            details.frame.url,
          );
      } catch {
        /* destroyed frame is rejected by the null snapshot below */
      }
    }
    const result = registry.beforeRequest(snapshot, details.requestHeaders);
    if (result.kind === 'authorized' && snapshot.frame && snapshot.webContentsId !== undefined) {
      const frames = observedFrames.get(snapshot.webContentsId) ?? new Set<number>();
      frames.add(snapshot.frame.frameTreeNodeId);
      observedFrames.set(snapshot.webContentsId, frames);
    }
    if (result.kind === 'blocked') callback({ cancel: true });
    else
      callback({
        requestHeaders:
          result.kind === 'authorized' ? result.requestHeaders : details.requestHeaders,
      });
  });
  session.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: registry.responseHeaders(details, details.responseHeaders ?? {}) });
  });
  session.webRequest.onCompleted((details) => registry.completeRequest(details.id));
  session.webRequest.onErrorOccurred((details) => registry.completeRequest(details.id));
  const installation = {
    registry,
    dispose: () => {
      clearInterval(frameSweep);
      observedFrames.clear();
      session.webRequest.onBeforeSendHeaders(null);
      session.webRequest.onHeadersReceived(null);
      session.webRequest.onCompleted(null);
      session.webRequest.onErrorOccurred(null);
      for (const { contents, navigation, destroyed } of watched.values()) {
        contents.off('did-start-navigation', navigation);
        contents.off('will-frame-navigate', navigation);
        contents.off('destroyed', destroyed);
      }
      watched.clear();
      installations.delete(session);
    },
  };
  installations.set(session, installation);
  return installation;
}

/** Navigate the exact bound frame; duplicate DOM names cannot intercept revocation. */
export async function blankSandboxDesktopGrantFrame(
  resolveOwner: ResolveOwner,
  ownerId: number,
  frameTreeNodeId: number,
): Promise<void> {
  const owner = resolveOwner(ownerId);
  if (!owner || owner.isDestroyed()) return;
  const find = (): WebFrameMain | undefined => {
    if (owner.isDestroyed()) return undefined;
    return owner.mainFrame.framesInSubtree.find(
      (frame) => frame.frameTreeNodeId === frameTreeNodeId,
    );
  };
  const frame = find();
  if (!frame) return;
  if (frame === owner.mainFrame || frame.parent !== owner.mainFrame)
    throw new Error('sandbox_desktop_grant_frame_mismatch');
  const navigation = frame.executeJavaScript('window.location.replace("about:blank")');
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      navigation,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error('sandbox_desktop_grant_frame_close_timeout')),
          5000,
        );
      }),
    ]);
  } catch {
    throw new Error('sandbox_desktop_grant_frame_close_failed');
  } finally {
    if (timer) clearTimeout(timer);
  }
  const deadline = Date.now() + 5000;
  while (true) {
    const current = find();
    if (!current || current.url === 'about:blank') return;
    if (Date.now() >= deadline) throw new Error('sandbox_desktop_grant_frame_close_timeout');
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}
function networkDetails(
  details: Readonly<{
    id: number;
    url: string;
    method: string;
    resourceType: string;
    webContentsId?: number;
    frame?: WebFrameMain | null;
  }>,
): SandboxDesktopGrantNetworkDetails {
  let frame: SandboxDesktopGrantNetworkDetails['frame'] = null;
  try {
    if (details.frame && !details.frame.isDestroyed())
      frame = {
        frameTreeNodeId: details.frame.frameTreeNodeId,
        parentFrameTreeNodeId: details.frame.parent?.frameTreeNodeId ?? null,
        name: details.frame.name,
      };
  } catch {
    /* Electron may remove a frame between delivery and observation. */
  }
  return {
    id: details.id,
    url: details.url,
    method: details.method,
    resourceType: details.resourceType,
    webContentsId: details.webContentsId,
    frame,
  };
}
