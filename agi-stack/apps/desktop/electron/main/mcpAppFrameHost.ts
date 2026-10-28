import type { WebContents } from 'electron';
import { randomUUID } from 'node:crypto';
import type { McpAppFrames, McpAppMount } from './mcpAppFrames';

const MAX_PENDING_APP_OPERATIONS = 32;

type CancellationResult = { cancelled: boolean; outcome: 'before_dispatch' | 'confirmed' | 'completed' | 'not_pending' | 'unknown' };
type PendingOperation = {
  mount: McpAppMount;
  input: Record<string, unknown>;
  controller: AbortController;
  started: boolean;
  completion?: Promise<unknown>;
  cancellation?: Promise<CancellationResult>;
};

/** Couples the verified Electron frame lifetime to the private sidecar mount. */
export class McpAppFrameHost {
  #lifetime = 0;
  readonly #operations = new Map<string, PendingOperation>();

  constructor(
    private readonly frames: McpAppFrames,
    private readonly invoke: (input: Record<string, unknown>) => Promise<unknown>,
    private readonly invokeCancellable?: (input: Record<string, unknown>, signal: AbortSignal) => Promise<unknown>,
  ) {}

  async register(owner: WebContents, input: unknown): Promise<unknown> {
    const lifetime = this.#lifetime;
    const mount = await this.frames.register(owner, input);
    const expired = () => lifetime !== this.#lifetime || !this.frames.isCurrent(mount);
    let result: unknown;
    try {
      result = await this.invoke({
        tabId: mount.tabId,
        operation: 'attach',
        mountNonce: mount.frameName,
      });
    } catch (error) {
      if (expired()) await this.unregister(mount).catch(() => {});
      else this.frames.remove(mount);
      throw error;
    }
    if (expired()) {
      await this.unregister(mount).catch(() => {});
      throw new Error('mcp_app_frame_expired');
    }
    return result;
  }

  async unregister(input: unknown): Promise<unknown> {
    const mount = this.frames.cancel(input);
    await this.cancelMount(mount);
    return this.detach(mount);
  }

  prepare(input: Record<string, unknown> | undefined): { operationId: string } {
    const mount = this.frames.requireCurrentMount(input);
    if (input?.operation !== 'tools/call' || !this.invokeCancellable) {
      throw new Error('mcp_app_operation_forbidden');
    }
    if (this.#operations.size >= MAX_PENDING_APP_OPERATIONS) throw new Error('mcp_app_operations_busy');
    const operationId = randomUUID();
    this.#operations.set(operationId, {
      mount, input: { tabId: mount.tabId, mountNonce: mount.frameName,
        operation: 'tools/call', arguments: structuredClone(input.arguments ?? {}) },
      controller: new AbortController(), started: false,
    });
    return { operationId };
  }

  async cancel(input: Record<string, unknown> | undefined): Promise<CancellationResult> {
    const operation = this.requireOperation(input, false);
    if (!operation) return { cancelled: false, outcome: 'not_pending' };
    return this.cancelOperation(input!.operationId as string, operation);
  }

  private requireOperation(input: Record<string, unknown> | undefined, required: boolean) {
    if (typeof input?.operationId !== 'string') throw new Error('mcp_app_operation_unavailable');
    const operation = this.#operations.get(input.operationId);
    if (!operation) {
      if (required) throw new Error('mcp_app_operation_unavailable');
      return undefined;
    }
    if (input.tabId !== operation.mount.tabId || input.mountNonce !== operation.mount.frameName) {
      throw new Error('mcp_app_frame_expired');
    }
    return operation;
  }

  async operation(input: Record<string, unknown> | undefined): Promise<unknown> {
    const lifetime = this.#lifetime;
    const mount = this.frames.requireCurrentMount(input);
    if (input?.operation === 'tools/call') {
      const operation = this.requireOperation(input, true)!;
      if (operation.started || operation.controller.signal.aborted) throw new Error('mcp_app_operation_cancelled');
      operation.started = true;
      try {
        operation.completion = this.invokeCancellable!(operation.input, operation.controller.signal);
        const result = await operation.completion;
        if (operation.controller.signal.aborted) throw new DOMException('MCP App request cancelled', 'AbortError');
        if (lifetime !== this.#lifetime || !this.frames.isCurrent(mount)) throw new Error('mcp_app_frame_expired');
        return result;
      } finally {
        this.#operations.delete(input.operationId as string);
      }
    }
    const result = await this.invoke({
      ...input,
      tabId: mount.tabId,
      mountNonce: mount.frameName,
    });
    if (lifetime !== this.#lifetime || !this.frames.isCurrent(mount)) {
      throw new Error('mcp_app_frame_expired');
    }
    return result;
  }

  async clear(): Promise<void> {
    this.#lifetime += 1;
    const cancellations = [...this.#operations].map(([id, operation]) => this.cancelOperation(id, operation));
    // Retire pending and retryable mounts too: the sidecar may already have
    // applied an attach whose response has not reached this process yet.
    await Promise.allSettled([...cancellations, ...this.frames.clear().map((mount) => this.detach(mount))]);
  }

  private detach(mount: McpAppMount): Promise<unknown> {
    return this.invoke({ tabId: mount.tabId, operation: 'detach', mountNonce: mount.frameName });
  }

  private async cancelMount(mount: McpAppMount): Promise<void> {
    const cancellations = [];
    for (const [id, operation] of this.#operations) {
      if (operation.mount.tabId === mount.tabId && operation.mount.frameName === mount.frameName) {
        cancellations.push(this.cancelOperation(id, operation));
      }
    }
    await Promise.all(cancellations);
  }

  private cancelOperation(id: string, operation: PendingOperation): Promise<CancellationResult> {
    operation.cancellation ??= (async (): Promise<CancellationResult> => {
      operation.controller.abort();
      if (!operation.started) {
        this.#operations.delete(id);
        return { cancelled: true, outcome: 'before_dispatch' };
      }
      try {
        await operation.completion;
        return { cancelled: false, outcome: 'completed' };
      } catch (error) {
        const confirmed = error instanceof Error && 'cancellationConfirmed' in error
          && error.cancellationConfirmed === true;
        return { cancelled: confirmed, outcome: confirmed ? 'confirmed' : 'unknown' };
      }
    })();
    return operation.cancellation;
  }
}
