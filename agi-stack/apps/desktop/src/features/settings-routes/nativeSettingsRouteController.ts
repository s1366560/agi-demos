import { nativeRouteFailure } from './nativeRouteHttpClient';
import type {
  NativeSettingsRouteObservation,
  NativeSettingsRoutePresentationInput,
  NativeSettingsRouteScope,
} from './nativeSettingsRoutePresentation';

export type NativeSettingsRouteController<TScope, TModel> = Readonly<{
  getSnapshot: () => TModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: TScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createNativeSettingsRouteController<
  TScope extends NativeSettingsRouteScope,
  TObservation extends NativeSettingsRouteObservation<TScope>,
  TModel,
>({
  client,
  initialScope,
  sameScope,
  present,
  fallbackReasonCode,
}: Readonly<{
  client: Readonly<{
    observe(scope: TScope, signal?: AbortSignal): Promise<TObservation>;
  }>;
  initialScope: TScope;
  sameScope: (left: TScope, right: TScope) => boolean;
  present: (input: NativeSettingsRoutePresentationInput<TScope, TObservation>) => TModel;
  fallbackReasonCode: string;
}>): NativeSettingsRouteController<TScope, TModel> {
  let activeScope = freezeScope(initialScope);
  let model = present({
    kind: 'loading',
    scope: activeScope,
    scopeSwitch: false,
  });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: TModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: TScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit(present({ kind: 'loading', scope, scopeSwitch }));
    try {
      const observation = await client.observe(scope, controller.signal);
      if (!requestIsCurrent(revision, controller)) return;
      emit(present({ kind: 'observed', observation }));
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) return;
      const failure = nativeRouteFailure(error, fallbackReasonCode);
      emit(
        present({
          kind: 'failure',
          scope,
          state: failure.state,
          reasonCode: failure.reasonCode,
          retryable: failure.retryable,
        }),
      );
    } finally {
      if (requestIsCurrent(revision, controller)) requestController = null;
    }
  };
  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    load,
    retry: () => load(activeScope),
    cancel,
    stop: cancel,
  });

  function requestIsCurrent(revision: number, controller: AbortController): boolean {
    return (
      revision === requestRevision && requestController === controller && !controller.signal.aborted
    );
  }
}

function freezeScope<TScope extends NativeSettingsRouteScope>(scope: TScope): TScope {
  return Object.freeze({ ...scope }) as TScope;
}
