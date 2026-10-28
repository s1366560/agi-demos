import type { ComputerUseOperation, ComputerUseSnapshot } from '../../api/computerUseContractV2';
import {
  computerUseInputIsVisible,
  parseComputerUseInputEvent,
  sameComputerUseInputScope,
  type ComputerUseInput,
  type ComputerUseInputScope,
} from '../../api/computerUseInput';

type Session = ComputerUseSnapshot['sessions'][number];
type Frames = {
  request: (callback: () => void) => number;
  cancel: (id: number) => void;
};

/** A single scoped subscription, with at most one rendered sample per session per frame. */
export function createComputerUseInputStore(scope: ComputerUseInputScope, frames: Frames) {
  let sessions = new Map<string, Session>();
  let frame: number | null = null;
  const values = new Map<string, ComputerUseInput>();
  const queued = new Map<string, ComputerUseInput>();
  const waiting = new Map<string, ComputerUseInput>();
  const sequences = new Map<string, { generation: string; sequence: number }>();
  const retired = new Map<string, Set<string>>();
  const listeners = new Map<string, Set<() => void>>();
  const notify = (id: string) => listeners.get(id)?.forEach((listener) => listener());
  const rememberPending = (input: ComputerUseInput) => {
    const pending = waiting.get(input.session_id);
    if (pending?.input_generation === input.input_generation && input.sequence <= pending.sequence)
      return;
    waiting.set(input.session_id, input);
    if (waiting.size > 128) waiting.delete(waiting.keys().next().value!);
  };

  const retire = (id: string, generation: string | null | undefined) => {
    if (!generation) return;
    const entries = retired.get(id) ?? new Set<string>();
    entries.add(generation);
    if (entries.size > 128) entries.delete(entries.values().next().value!);
    retired.set(id, entries);
  };
  const clear = (id: string, invalidate: boolean) => {
    if (invalidate) {
      retire(id, sessions.get(id)?.input_generation);
      retire(id, values.get(id)?.input_generation);
      retire(id, queued.get(id)?.input_generation);
    }
    queued.delete(id);
    waiting.delete(id);
    if (values.delete(id)) notify(id);
    if (!queued.size && frame !== null) {
      frames.cancel(frame);
      frame = null;
    }
  };
  const matchesOwner = (input: ComputerUseInput) => {
    const session = sessions.get(input.session_id);
    return (
      !!session &&
      !session.stopped &&
      input.conversation_id === session.conversation_id &&
      input.run_id === session.run_id &&
      (!session.input_mode || input.input_mode === session.input_mode) &&
      !retired.get(input.session_id)?.has(input.input_generation)
    );
  };
  const active = (session: Session) =>
    !session.stopped &&
    !['paused', 'stopped', 'awaiting_permission', 'focus_required', 'error'].includes(
      session.presentation?.phase ?? 'idle',
    );
  const matches = (input: ComputerUseInput) =>
    matchesOwner(input) && active(sessions.get(input.session_id)!);
  const flush = () => {
    frame = null;
    const updates = [...queued.values()];
    queued.clear();
    for (const input of updates) {
      if (
        !matches(input) ||
        input.input_generation !== sessions.get(input.session_id)?.input_generation
      )
        continue;
      values.set(input.session_id, input);
      notify(input.session_id);
    }
  };
  const receiveInput = (input: ComputerUseInput) => {
    if (!sessions.has(input.session_id)) {
      rememberPending(input);
      return;
    }
    if (!matchesOwner(input)) return;
    const previous = sequences.get(input.session_id);
    if (previous?.generation === input.input_generation && input.sequence <= previous.sequence)
      return;
    const session = sessions.get(input.session_id)!;
    if (!active(session)) {
      if (session.presentation?.phase !== 'stopped') rememberPending(input);
      return;
    }
    if (input.input_generation !== sessions.get(input.session_id)?.input_generation) {
      rememberPending(input);
      return;
    }
    if (previous && previous.generation !== input.input_generation)
      retire(input.session_id, previous.generation);
    sequences.set(input.session_id, {
      generation: input.input_generation,
      sequence: input.sequence,
    });
    if (!computerUseInputIsVisible(input)) {
      if (input.phase !== 'error') retire(input.session_id, input.input_generation);
      clear(input.session_id, input.phase !== 'error');
      return;
    }
    queued.set(input.session_id, input);
    if (frame === null) frame = frames.request(flush);
  };

  return {
    subscribe(id: string, listener: () => void): () => void {
      const entries = listeners.get(id) ?? new Set<() => void>();
      entries.add(listener);
      listeners.set(id, entries);
      return () => {
        entries.delete(listener);
        if (!entries.size) listeners.delete(id);
      };
    },
    getSnapshot: (id: string): ComputerUseInput | null => values.get(id) ?? null,
    receive(value: unknown): void {
      const event = parseComputerUseInputEvent(value);
      if (!event) return;
      const identity = event.type === 'computer_use_input' ? event.input : event;
      if (!sameComputerUseInputScope(identity, scope)) return;
      if (event.type === 'computer_use_input') receiveInput(event.input);
      else if (event.session_id) clear(event.session_id, true);
      else for (const id of sessions.keys()) clear(id, true);
    },
    updateSnapshot(snapshot: ComputerUseSnapshot): void {
      if (
        snapshot.scope.tenant_id !== scope.tenant_id ||
        snapshot.scope.project_id !== scope.project_id
      )
        return;
      const previous = sessions;
      sessions = new Map(snapshot.sessions.map((session) => [session.session_id, session]));
      for (const [id, session] of previous) {
        if (!sessions.has(id)) {
          clear(id, true);
          retired.delete(id);
          sequences.delete(id);
        } else if (
          session.input_generation &&
          session.input_generation !== sessions.get(id)?.input_generation
        ) {
          if (sessions.get(id)?.input_generation) retire(id, session.input_generation);
          queued.delete(id);
          if (values.delete(id)) notify(id);
        }
      }
      for (const session of sessions.values()) {
        if (
          session.stopped ||
          ['paused', 'stopped', 'awaiting_permission', 'focus_required', 'error'].includes(
            session.presentation?.phase ?? 'idle',
          )
        ) {
          const pending = waiting.get(session.session_id);
          clear(
            session.session_id,
            session.stopped ||
              ['paused', 'stopped'].includes(session.presentation?.phase ?? 'idle'),
          );
          if (
            pending &&
            !session.stopped &&
            session.presentation?.phase !== 'stopped' &&
            !retired.get(session.session_id)?.has(pending.input_generation)
          )
            rememberPending(pending);
          continue;
        }
        const pending = waiting.get(session.session_id);
        if (pending && pending.input_generation === session.input_generation) {
          waiting.delete(session.session_id);
          receiveInput(pending);
        }
      }
    },
    willManage(operation: ComputerUseOperation): void {
      if (
        !['pause', 'stop', 'stop_all', 'disable', 'uninstall', 'set_input_mode'].includes(
          operation.action,
        )
      )
        return;
      const invalidate = ['pause', 'stop', 'stop_all'].includes(operation.action);
      for (const id of sessions.keys())
        if (!operation.session_id || operation.session_id === id)
          clear(id, invalidate);
    },
    dispose(): void {
      for (const id of sessions.keys()) clear(id, false);
      if (frame !== null) frames.cancel(frame);
      frame = null;
      sessions.clear();
      queued.clear();
      waiting.clear();
      values.clear();
      sequences.clear();
      retired.clear();
    },
  };
}

export type ComputerUseInputStore = ReturnType<typeof createComputerUseInputStore>;
