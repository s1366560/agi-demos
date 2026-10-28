import type {
  ComputerUseOperation,
  ComputerUseSnapshot,
} from '../../src/api/computerUseContractV2';
import {
  parseComputerUseInput,
  sameComputerUseInputScope,
  type ComputerUseInput,
  type ComputerUseInputEvent,
  type ComputerUseInputScope,
} from '../../src/api/computerUseInput';

type Session = ComputerUseSnapshot['sessions'][number];
type Scope = ComputerUseInputScope & { readonly credential: string };
type Binding = {
  ownerId: number;
  scope: Scope;
  sessions: ReadonlyMap<string, Session>;
};
type Receipt = { generation: string; sequence: number };

/** The existing management binding is the only authority for renderer telemetry. */
export class ComputerUseInputMonitor {
  private binding: Binding | null = null;
  private readonly receipts = new Map<string, Receipt>();
  private readonly pending = new Map<string, ComputerUseInput>();
  private readonly retired = new Map<string, Set<string>>();

  constructor(private readonly emit: (ownerId: number, event: ComputerUseInputEvent) => void) {}

  bind(ownerId: number, scope: Scope, snapshot: ComputerUseSnapshot): void {
    if (
      this.binding &&
      (this.binding.ownerId !== ownerId ||
        !sameComputerUseInputScope(this.binding.scope, scope) ||
        this.binding.scope.credential !== scope.credential)
    )
      this.clear();
    const previous = this.binding?.sessions;
    const sessions = new Map(snapshot.sessions.map((session) => [session.session_id, session]));
    this.binding = { ownerId, scope, sessions };
    for (const [id, input] of this.pending)
      if (!sameComputerUseInputScope(input, scope)) this.pending.delete(id);
    for (const [id, session] of previous ?? []) {
      if (!sessions.has(id)) {
        this.resetSession(id, session.input_generation);
        this.pending.delete(id);
        this.retired.delete(id);
      }
    }
    for (const session of sessions.values()) {
      if (!activeSession(session)) {
        if (
          session.stopped ||
          ['paused', 'stopped'].includes(session.presentation?.phase ?? 'idle')
        )
          this.resetSession(session.session_id, session.input_generation);
        const pending = this.pending.get(session.session_id);
        if (
          session.stopped ||
          session.presentation?.phase === 'stopped' ||
          (pending && this.retired.get(session.session_id)?.has(pending.input_generation))
        )
          this.pending.delete(session.session_id);
        continue;
      }
      const old = previous?.get(session.session_id)?.input_generation;
      if (old && session.input_generation && old !== session.input_generation)
        this.retire(session.session_id, old);
      const pending = this.pending.get(session.session_id);
      if (pending && pending.input_generation === session.input_generation) {
        this.pending.delete(session.session_id);
        this.receive(pending);
      }
    }
  }

  receive(value: unknown): void {
    const input = parseComputerUseInput(value);
    const binding = this.binding;
    if (!input || (binding && !sameComputerUseInputScope(input, binding.scope))) return;
    const session = binding?.sessions.get(input.session_id);
    if (!binding || !session) {
      this.rememberPending(input);
      return;
    }
    if (
      input.conversation_id !== session.conversation_id ||
      input.run_id !== session.run_id ||
      (session.input_mode !== undefined && input.input_mode !== session.input_mode) ||
      this.retired.get(input.session_id)?.has(input.input_generation)
    )
      return;
    const receipt = this.receipts.get(input.session_id);
    if (receipt?.generation === input.input_generation && input.sequence <= receipt.sequence)
      return;
    if (!activeSession(session)) {
      if (!session.stopped && session.presentation?.phase !== 'stopped')
        this.rememberPending(input);
      return;
    }
    // A new native generation may arrive before the next low-frequency status read.
    // Retain one sample, then release it only when that read binds the generation.
    if (input.input_generation !== session.input_generation) {
      this.rememberPending(input);
      return;
    }
    if (input.phase === 'paused' || input.phase === 'stopped') {
      this.resetSession(input.session_id, input.input_generation);
      this.pending.delete(input.session_id);
      return;
    }
    if (receipt && receipt.generation !== input.input_generation)
      this.retire(input.session_id, receipt.generation);
    this.receipts.set(input.session_id, {
      generation: input.input_generation,
      sequence: input.sequence,
    });
    this.emit(binding.ownerId, { type: 'computer_use_input', input });
  }

  willManage(operation: ComputerUseOperation): void {
    if (!this.binding) return;
    // Revision-guarded instance changes retire inputs when their stopped snapshot binds.
    if (!['pause', 'stop', 'stop_all'].includes(operation.action)) return;
    for (const session of this.binding.sessions.values()) {
      if (operation.session_id && operation.session_id !== session.session_id) continue;
      this.resetSession(session.session_id, session.input_generation);
      this.pending.delete(session.session_id);
    }
  }

  clear(ownerId?: number): void {
    if (this.binding && ownerId !== undefined && ownerId !== this.binding.ownerId) return;
    if (this.binding)
      this.emit(this.binding.ownerId, {
        type: 'computer_use_input_reset',
        mode: this.binding.scope.mode,
        tenant_id: this.binding.scope.tenant_id,
        project_id: this.binding.scope.project_id,
      });
    this.binding = null;
    this.pending.clear();
    this.receipts.clear();
    this.retired.clear();
  }

  private rememberPending(input: ComputerUseInput): void {
    const pending = this.pending.get(input.session_id);
    if (pending?.input_generation === input.input_generation && input.sequence <= pending.sequence)
      return;
    this.pending.set(input.session_id, input);
    if (this.pending.size > 128) this.pending.delete(this.pending.keys().next().value!);
  }

  private resetSession(id: string, generation?: string | null): void {
    const binding = this.binding;
    if (!binding) return;
    if (generation) this.retire(id, generation);
    const receipt = this.receipts.get(id);
    if (receipt) this.retire(id, receipt.generation);
    this.receipts.delete(id);
    this.emit(binding.ownerId, {
      type: 'computer_use_input_reset',
      mode: binding.scope.mode,
      tenant_id: binding.scope.tenant_id,
      project_id: binding.scope.project_id,
      session_id: id,
    });
  }

  private retire(id: string, generation: string): void {
    const generations = this.retired.get(id) ?? new Set<string>();
    generations.add(generation);
    if (generations.size > 128) generations.delete(generations.values().next().value!);
    this.retired.set(id, generations);
  }
}

function activeSession(session: Session): boolean {
  return (
    !session.stopped &&
    !['paused', 'stopped', 'awaiting_permission', 'focus_required', 'error'].includes(
      session.presentation?.phase ?? 'idle',
    )
  );
}
