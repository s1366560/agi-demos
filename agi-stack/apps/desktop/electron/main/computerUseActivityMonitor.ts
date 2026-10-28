import {
  isComputerUseSnapshotForScope,
  type ComputerUseSnapshot,
} from '../../src/api/computerUseContractV2';
import { computerUseRecordingIsPending } from '../../src/api/computerUseRecording';
import type { ComputerUseOperation } from '../../src/api/computerUseContractV2';
import type { ComputerUseInputMonitor } from './computerUseInputMonitor';

type Input = Readonly<{
  mode: 'local' | 'cloud';
  tenant_id: string;
  project_id: string;
  credential: string;
}>;
type Binding = Readonly<{ ownerId: number; input: Input; generation: number }>;
type Management = Readonly<{ ownerId: number; input: Input }>;
export interface ComputerUseActivitySurface {
  update(
    snapshot: ComputerUseSnapshot,
    actions: {
      show: () => void;
      manage: (operation: Record<string, unknown>) => Promise<void>;
      preview: (id: string) => Promise<string>;
    }
  ): void;
  hide(): void;
}
export class ComputerUseActivityMonitor {
  private binding: Binding | null = null;
  private sequence = 0;
  private management: Management | null = null;
  private readonly pending = new Set<{ ownerId: number }>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  constructor(
    private readonly ports: {
      invoke: (args: Record<string, unknown>) => Promise<unknown>;
      emit: (ownerId: number, snapshot: ComputerUseSnapshot, mode: Input['mode']) => void;
      show: () => void;
      surface: ComputerUseActivitySurface;
      inputs?: ComputerUseInputMonitor;
    }
  ) {}
  async track(ownerId: number, args: Record<string, unknown> | undefined): Promise<unknown> {
    const input = parseInput(args?.input);
    const operation = (args?.input as { operation?: { action?: string } } | undefined)?.operation
      ?.action;
    if (operation === 'artifact_preview' || operation === 'audio_chunk')
      return this.ports.invoke(args ?? {});
    if (input && operation && this.binding?.ownerId === ownerId &&
      sameInput(this.binding.input, input)) {
      this.ports.inputs?.willManage(
        (args?.input as { operation: ComputerUseOperation }).operation,
      );
    }
    if (
      input &&
      this.management &&
      (this.management.ownerId !== ownerId || !sameInput(this.management.input, input))
    )
      this.management = null;
    const receipt = input && operation !== 'status' ? { ownerId, input } : null;
    const statusDuringManagement = !receipt && this.management !== null;
    if (receipt) this.management = receipt;
    const sequence = ++this.sequence;
    const pending = { ownerId };
    this.pending.add(pending);
    try {
      const result = await this.ports.invoke(args ?? {});
      const current =
        this.pending.has(pending) &&
        (receipt
          ? this.management === receipt
          : !statusDuringManagement && this.management === null && sequence === this.sequence);
      if (receipt && current) {
        this.management = null;
        this.sequence++;
      }
      if (
        input &&
        current &&
        isComputerUseSnapshotForScope(result, {
          tenantId: input.tenant_id,
          projectId: input.project_id,
        })
      ) {
        const generation = (this.binding?.generation ?? 0) + 1;
        this.binding = { ownerId, input, generation };
        this.publish(this.binding, result);
      }
      return result;
    } finally {
      this.pending.delete(pending);
      if (receipt && this.management === receipt) {
        this.management = null;
        this.sequence++;
      }
    }
  }
  clear(ownerId?: number): void {
    const ownsBinding = ownerId === undefined || this.binding?.ownerId === ownerId;
    const ownsManagement = ownerId === undefined || this.management?.ownerId === ownerId;
    let ownsPending = false;
    for (const pending of this.pending) {
      if (ownerId === undefined || pending.ownerId === ownerId) {
        this.pending.delete(pending);
        ownsPending = true;
      }
    }
    if (!ownsBinding && !ownsManagement && !ownsPending) return;
    if (ownsBinding || ownsManagement) this.sequence++;
    if (ownsManagement) this.management = null;
    this.ports.inputs?.clear(ownerId);
    if (!ownsBinding) return;
    this.binding = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    this.ports.surface.hide();
  }
  private publish(binding: Binding, snapshot: ComputerUseSnapshot): void {
    if (this.binding !== binding) return;
    this.ports.inputs?.bind(binding.ownerId, binding.input, snapshot);
    this.ports.emit(binding.ownerId, snapshot, binding.input.mode);
    this.ports.surface.update(snapshot, {
      show: this.ports.show,
      manage: async (operation) => {
        if (this.binding !== binding) throw new Error('cua_activity_scope_expired');
        await this.track(binding.ownerId, {
          input: { ...binding.input, operation },
        });
      },
      preview: async (id) => {
        if (this.binding !== binding || !/^cua-image-[0-9a-f-]+$/u.test(id))
          throw new Error('cua_activity_scope_expired');
        const result = (await this.ports.invoke({
          input: {
            ...binding.input,
            operation: { action: 'artifact_preview', artifact_id: id },
          },
        })) as { artifact_id?: string; data_url?: string };
        if (
          this.binding !== binding ||
          result.artifact_id !== id ||
          typeof result.data_url !== 'string' ||
          !/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/u.test(result.data_url)
        )
          throw new Error('cua_preview_invalid');
        return result.data_url;
      },
    });
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(
      () => void this.poll(binding),
      snapshot.sessions.length || snapshot.pending.length ||
      snapshot.recordings?.some(computerUseRecordingIsPending) ? 1000 : 10000
    );
  }
  private async poll(binding: Binding): Promise<void> {
    if (this.binding !== binding) return;
    if (this.management) {
      this.timer = setTimeout(() => void this.poll(binding), 1000);
      return;
    }
    const sequence = ++this.sequence;
    try {
      const result = await this.ports.invoke({
        input: { ...binding.input, operation: { action: 'status' } },
      });
      if (
        this.binding === binding &&
        sequence === this.sequence &&
        isComputerUseSnapshotForScope(result, {
          tenantId: binding.input.tenant_id,
          projectId: binding.input.project_id,
        })
      ) {
        this.publish(binding, result);
        return;
      }
    } catch {
      if (this.binding === binding && sequence === this.sequence && !this.management)
        this.ports.surface.hide();
    }
    if (this.binding === binding) this.timer = setTimeout(() => void this.poll(binding), 5000);
  }
}
function sameInput(left: Input, right: Input): boolean {
  return (
    left.mode === right.mode &&
    left.tenant_id === right.tenant_id &&
    left.project_id === right.project_id &&
    left.credential === right.credential
  );
}
function parseInput(value: unknown): Input | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const input = value as Record<string, unknown>;
  if (
    !['local', 'cloud'].includes(input.mode as string) ||
    typeof input.tenant_id !== 'string' ||
    !input.tenant_id ||
    typeof input.project_id !== 'string' ||
    !input.project_id ||
    typeof input.credential !== 'string'
  )
    return null;
  return {
    mode: input.mode as Input['mode'],
    tenant_id: input.tenant_id,
    project_id: input.project_id,
    credential: input.credential,
  };
}
