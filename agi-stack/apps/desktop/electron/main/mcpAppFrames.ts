import type { WebContents } from 'electron';

type Frame = { id: string; parentId?: string; loaderId: string; name?: string; url: string };
type Tree = { frame: Frame; childFrames?: Tree[] };
type Target = { targetId: string; type: string; parentFrameId?: string };
type LocatedTree = { tree: Tree; sessionId?: string };
type Resolved = { host: Frame; outer: Frame; frame: Frame; sessionId?: string };
type Binding = {
  owner: WebContents;
  host: Frame;
  outer: Frame;
  frame: Frame;
  frameName: string;
};
export type McpAppMount = { tabId: string; frameName: string };

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('mcp_app_request_invalid');
  return value as Record<string, unknown>;
}
function identifier(value: unknown): string {
  if (typeof value !== 'string' || !/^mcpapp-[a-f0-9-]{36}$/u.test(value))
    throw new Error('mcp_app_tab_invalid');
  return value;
}
function sameDocument(first: Frame, second: Frame): boolean {
  return first.id === second.id && first.loaderId === second.loaderId && first.url === second.url;
}

/** Only the trusted host renderer can register; scripts come from the private bridge. */
export class McpAppFrames {
  constructor(private readonly isIsolatedOwner: (owner: WebContents) => boolean = () => false) {}

  readonly #bindings = new Map<string, Binding>();
  readonly #sessions = new Map<string, string>();
  readonly #cancelled = new Map<string, Set<string>>();
  readonly #mounts = new Map<string, McpAppMount>();
  #lifetime = 0;

  async register(owner: WebContents, input: unknown): Promise<McpAppMount> {
    const value = record(input);
    const tabId = identifier(value.tabId);
    const frameName = identifier(value.frameName);
    if (this.#cancelled.get(tabId)?.has(frameName)) throw new Error('mcp_app_mount_cancelled');
    this.#mounts.set(`${tabId}:${frameName}`, { tabId, frameName });
    const lifetime = this.#lifetime;
    const { host, outer, frame } = await this.#resolve(owner, frameName);
    if (this.#lifetime !== lifetime) throw new Error('mcp_app_frame_expired');
    if (this.#cancelled.get(tabId)?.has(frameName)) throw new Error('mcp_app_mount_cancelled');
    const prior = this.#bindings.get(tabId);
    if (prior) {
      if (
        prior.owner !== owner ||
        prior.frameName !== frameName ||
        !sameDocument(prior.host, host) ||
        !sameDocument(prior.outer, outer) ||
        !sameDocument(prior.frame, frame)
      )
        throw new Error('mcp_app_frame_already_bound');
      return { tabId, frameName };
    }
    this.#bindings.set(tabId, {
      owner,
      host: { ...host },
      outer: { ...outer },
      frame: { ...frame },
      frameName,
    });
    return { tabId, frameName };
  }

  isCurrent(mount: McpAppMount): boolean {
    return this.#bindings.get(mount.tabId)?.frameName === mount.frameName
      && !this.#cancelled.get(mount.tabId)?.has(mount.frameName);
  }

  requireCurrentMount(input: unknown): McpAppMount {
    const value = record(input);
    const tabId = identifier(value.tabId);
    const frameName = identifier(value.mountNonce);
    if (!this.#bindings.has(tabId)) throw new Error('mcp_app_frame_unavailable');
    const mount = { tabId, frameName };
    if (!this.isCurrent(mount)) throw new Error('mcp_app_frame_expired');
    return mount;
  }

  /** Retryable attach failures discard only their own binding. */
  remove(input: unknown): void {
    const value = record(input);
    const tabId = identifier(value.tabId);
    const frameName = identifier(value.frameName);
    if (this.#bindings.get(tabId)?.frameName === frameName) this.#bindings.delete(tabId);
  }

  /** A disposed effect cannot revive, including when discovery has not completed. */
  cancel(input: unknown): McpAppMount {
    const value = record(input);
    const tabId = identifier(value.tabId);
    const frameName = identifier(value.frameName);
    const cancelled = this.#cancelled.get(tabId) ?? new Set<string>();
    cancelled.add(frameName);
    this.#cancelled.set(tabId, cancelled);
    this.#mounts.set(`${tabId}:${frameName}`, { tabId, frameName });
    this.remove({ tabId, frameName });
    return { tabId, frameName };
  }

  clear(): McpAppMount[] {
    const mounts = [...this.#mounts.values()];
    this.#lifetime += 1;
    this.#bindings.clear();
    this.#sessions.clear();
    this.#cancelled.clear();
    this.#mounts.clear();
    return mounts;
  }

  async execute(input: unknown): Promise<unknown> {
    const value = record(input);
    const { tabId } = this.requireCurrentMount(value);
    const binding = this.#bindings.get(tabId)!;
    const target = await this.#current(tabId, binding);
    let output: unknown;
    if (value.operation === 'tab.screenshot') {
      if (!this.isIsolatedOwner(binding.owner)) throw new Error('mcp_app_capture_surface_unavailable');
      // Capture only the dedicated guest. Cropping the host would include native/DOM overlays.
      const rect = await binding.owner.executeJavaScriptInIsolatedWorld(1006, [
        {
          code: `(() => { const e = [...document.querySelectorAll('iframe')].find(e => e.name === ${JSON.stringify(binding.frameName)}); if (!e) throw Error('mcp_app_frame_missing'); const r=e.getBoundingClientRect(); return {x:Math.max(0,Math.ceil(r.x)),y:Math.max(0,Math.ceil(r.y)),width:Math.floor(Math.min(r.right,innerWidth)-Math.max(0,r.x)),height:Math.floor(Math.min(r.bottom,innerHeight)-Math.max(0,r.y))}; })()`,
        },
      ]);
      if (
        !rect ||
        !Number.isFinite(rect.width) ||
        !Number.isFinite(rect.height) ||
        rect.width < 1 ||
        rect.height < 1
      )
        throw new Error('mcp_app_frame_not_visible');
      await this.#current(tabId, binding);
      const screenshot = await binding.owner.capturePage(rect);
      if (!this.isIsolatedOwner(binding.owner)) throw new Error('mcp_app_capture_surface_unavailable');
      output = {
        data: screenshot.toPNG().toString('base64'),
        mimeType: 'image/png',
        width: screenshot.getSize().width,
        height: screenshot.getSize().height,
      };
    } else {
      if (typeof value.expression !== 'string' || value.expression.length > 2_000_000)
        throw new Error('mcp_app_expression_invalid');
      const sessionId = target.sessionId;
      const context = await binding.owner.debugger.sendCommand(
        'Page.createIsolatedWorld',
        {
          frameId: binding.frame.id,
          worldName: 'memstack-mcp-app-automation',
          grantUniveralAccess: false,
        },
        sessionId,
      );
      // A reload can keep the same frame id while creating a different document/world.
      await this.#current(tabId, binding);
      const result = await binding.owner.debugger.sendCommand(
        'Runtime.evaluate',
        {
          expression: value.expression,
          contextId: context.executionContextId,
          awaitPromise: true,
          returnByValue: true,
          timeout: 15_000,
        },
        sessionId,
      );
      if (result.exceptionDetails) throw new Error('mcp_app_dom_execution_failed');
      output = result.result?.value ?? null;
    }
    await this.#current(tabId, binding);
    if (JSON.stringify(output).length > 8_000_000) throw new Error('mcp_app_result_too_large');
    return output;
  }

  async #current(tabId: string, binding: Binding): Promise<Resolved> {
    if (this.#bindings.get(tabId) !== binding) throw new Error('mcp_app_frame_expired');
    let target: Resolved;
    try {
      target = await this.#resolve(binding.owner, binding.frameName, binding);
    } catch {
      throw new Error('mcp_app_frame_expired');
    }
    if (
      this.#bindings.get(tabId) !== binding ||
      !sameDocument(target.host, binding.host) ||
      !sameDocument(target.outer, binding.outer) ||
      !sameDocument(target.frame, binding.frame)
    )
      throw new Error('mcp_app_frame_expired');
    return target;
  }

  async #targetSession(owner: WebContents, targetId: string): Promise<string> {
    const key = `${owner.id}:${targetId}`;
    const prior = this.#sessions.get(key);
    if (prior) return prior;
    const lifetime = this.#lifetime;
    const attached = await owner.debugger.sendCommand('Target.attachToTarget', {
      targetId,
      flatten: true,
    });
    if (this.#lifetime !== lifetime) throw new Error('mcp_app_frame_expired');
    if (typeof attached.sessionId !== 'string')
      throw new Error('mcp_app_frame_session_unavailable');
    this.#sessions.set(key, attached.sessionId);
    return attached.sessionId;
  }

  async #child(
    owner: WebContents,
    parent: LocatedTree,
    frameId: string,
    targets: Target[],
  ): Promise<LocatedTree> {
    const remote = targets.find((target) => target.type === 'iframe' && target.targetId === frameId);
    let child: LocatedTree;
    if (remote) {
      // Never attach to a sibling or another page's target, even if its name matches.
      if (remote.parentFrameId !== parent.tree.frame.id)
        throw new Error('mcp_app_frame_invalid');
      const sessionId = await this.#targetSession(owner, frameId);
      try {
        const { frameTree } = (await owner.debugger.sendCommand(
          'Page.getFrameTree',
          {},
          sessionId,
        )) as { frameTree: Tree };
        child = { tree: frameTree, sessionId };
      } catch {
        this.#sessions.delete(`${owner.id}:${frameId}`);
        throw new Error('mcp_app_frame_expired');
      }
    } else {
      const tree = parent.tree.childFrames?.find((item) => item.frame.id === frameId);
      if (!tree) throw new Error('mcp_app_frame_not_ready');
      child = { tree, sessionId: parent.sessionId };
    }
    if (child.tree.frame.id !== frameId || child.tree.frame.parentId !== parent.tree.frame.id)
      throw new Error('mcp_app_frame_invalid');
    return child;
  }

  async #resolve(owner: WebContents, name: string, expected?: Binding): Promise<Resolved> {
    if (owner.isDestroyed()) throw new Error('mcp_app_frame_expired');
    if (!owner.debugger.isAttached()) owner.debugger.attach('1.3');
    const { frameTree } = (await owner.debugger.sendCommand('Page.getFrameTree')) as {
      frameTree: Tree;
    };
    if (expected && !sameDocument(frameTree.frame, expected.host))
      throw new Error('mcp_app_frame_expired');
    // OOPIFs are omitted from their parent's frame tree. Resolve the exact host-owned
    // iframe node first, then follow only its verified direct descendants' sessions.
    const { root } = await owner.debugger.sendCommand('DOM.getDocument', { depth: 1 });
    const { nodeIds } = await owner.debugger.sendCommand('DOM.querySelectorAll', {
      nodeId: root.nodeId,
      selector: `iframe[name="${name}"]`,
    });
    if (nodeIds.length !== 1) throw new Error('mcp_app_frame_not_ready');
    const { node } = await owner.debugger.sendCommand('DOM.describeNode', { nodeId: nodeIds[0] });
    if (typeof node.frameId !== 'string') throw new Error('mcp_app_frame_not_ready');
    if (expected && node.frameId !== expected.outer.id)
      throw new Error('mcp_app_frame_expired');
    const { targetInfos } = (await owner.debugger.sendCommand('Target.getTargets')) as {
      targetInfos: Target[];
    };
    const outer = await this.#child(owner, { tree: frameTree }, node.frameId, targetInfos);
    // CDP retains the navigation-time name when the host renames a loaded iframe.
    // The exact host DOM node above supplies its live frame id; #child verifies
    // direct ancestry, and the document checks below pin that frame across calls.
    if (expected && !sameDocument(outer.tree.frame, expected.outer))
      throw new Error('mcp_app_frame_expired');
    const children = new Set([
      ...(outer.tree.childFrames ?? []).map((child) => child.frame.id),
      ...targetInfos
        .filter((target) => target.type === 'iframe' && target.parentFrameId === outer.tree.frame.id)
        .map((target) => target.targetId),
    ]);
    if (children.size !== 1) throw new Error('mcp_app_frame_not_ready');
    if (expected && !children.has(expected.frame.id))
      throw new Error('mcp_app_frame_expired');
    const app = await this.#child(owner, outer, [...children][0], targetInfos);
    const documents = [frameTree.frame, outer.tree.frame, app.tree.frame];
    if (documents.some((frame) => typeof frame.loaderId !== 'string' || !frame.loaderId))
      throw new Error('mcp_app_frame_not_ready');
    return {
      host: frameTree.frame,
      outer: outer.tree.frame,
      frame: app.tree.frame,
      sessionId: app.sessionId,
    };
  }
}
