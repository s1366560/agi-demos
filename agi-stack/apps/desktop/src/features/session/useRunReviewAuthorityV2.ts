import { useCallback, useEffect, useMemo, useRef } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type {
  AgentConversation,
  ChangeSnapshot,
  CodeRangeReference,
  DesktopRun,
  DesktopRuntimeConfig,
  RunSummary,
} from '../../types';
import type { RunChangeScope } from '../agent-authority/agentAuthorityTypes';
import type { DesktopSessionProjectionOperationsV2 } from '../../plugins/desktopSessionProjectionAuthorityModuleV2';
import type { DesktopSessionRunChangesOperationsV2 } from '../../plugins/desktopSessionRunChangesAuthorityModuleV2';
import { formatConnectionError } from '../../utils/format';

type Options = {
  config: DesktopRuntimeConfig;
  conversation: AgentConversation | null;
  run: DesktopRun | null;
  scope: RunChangeScope;
  projectionOperations: DesktopSessionProjectionOperationsV2;
  changesOperations: DesktopSessionRunChangesOperationsV2;
  setSummary: Dispatch<SetStateAction<RunSummary | null>>;
  setSnapshot: Dispatch<SetStateAction<ChangeSnapshot | null>>;
  setLoading: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setReferences: Dispatch<SetStateAction<CodeRangeReference[]>>;
};

export function useRunReviewAuthorityV2({
  config,
  conversation,
  run,
  scope,
  projectionOperations,
  changesOperations,
  setSummary,
  setSnapshot,
  setLoading,
  setError,
  setReferences,
}: Options) {
  const context = useMemo(
    () => ({ config, conversation, run, projectionOperations, changesOperations }),
    [config, conversation, run, projectionOperations, changesOperations],
  );
  const contextRef = useRef(context);
  contextRef.current = context;
  const changeContext = useMemo(() => ({ context, scope }), [context, scope]);
  const changeContextRef = useRef(changeContext);
  changeContextRef.current = changeContext;
  const lifetimeRef = useRef<{
    context: typeof changeContext;
    controller: AbortController;
    request: AbortController | null;
  } | null>(null);
  const bound = Boolean(
    conversation &&
    run &&
    run.conversation_id === conversation.id &&
    run.project_id === conversation.project_id &&
    run.project_id === config.projectId,
  );

  useEffect(() => {
    const controller = new AbortController();
    setSummary(null);
    if (config.mode === 'cloud' && bound && conversation && run) {
      void projectionOperations
        .getRunSummary({ config, conversation, runId: run.id, signal: controller.signal })
        .then((summary) => {
          if (!controller.signal.aborted && contextRef.current === context) setSummary(summary);
        })
        .catch(() => {
          if (!controller.signal.aborted && contextRef.current === context) setSummary(null);
        });
    }
    return () => controller.abort();
  }, [context, config, conversation, run, bound, projectionOperations, setSummary]);

  const loadRunChanges = useCallback(
    async (signal?: AbortSignal) => {
      const lifetime = lifetimeRef.current;
      if (
        !lifetime ||
        lifetime.context !== changeContext ||
        changeContextRef.current !== changeContext ||
        lifetime.controller.signal.aborted ||
        signal?.aborted
      )
        return;
      lifetime.request?.abort();
      const request = new AbortController();
      lifetime.request = request;
      const abort = () => request.abort();
      signal?.addEventListener('abort', abort, { once: true });
      const ownsRequest = () =>
        lifetimeRef.current === lifetime &&
        changeContextRef.current === changeContext &&
        !lifetime.controller.signal.aborted &&
        lifetime.request === request;
      const current = () => ownsRequest() && !request.signal.aborted;
      setSnapshot(null);
      setError(null);
      if (!bound || !conversation || !run) {
        setLoading(false);
        signal?.removeEventListener('abort', abort);
        return;
      }
      setLoading(true);
      try {
        if (config.mode === 'local' && scope !== 'run')
          throw new Error('local_run_changes_scope_unavailable');
        const snapshot = await changesOperations.getRunChanges({
          config,
          conversation,
          runId: run.id,
          expectedRevision: run.revision,
          scope,
          ...(scope === 'turn' ? { turnId: run.message_id } : {}),
          signal: request.signal,
        });
        if (!current()) return;
        setSnapshot(snapshot);
        setReferences((references) =>
          references.filter(
            (reference) =>
              reference.snapshot_id === snapshot.id &&
              reference.environment_id === snapshot.environment_id,
          ),
        );
      } catch (error) {
        if (current()) setError(formatConnectionError(error, config.apiBaseUrl));
      } finally {
        signal?.removeEventListener('abort', abort);
        if (ownsRequest()) setLoading(false);
      }
    },
    [
      changeContext,
      bound,
      config,
      conversation,
      run,
      scope,
      changesOperations,
      setSnapshot,
      setLoading,
      setError,
      setReferences,
    ],
  );

  useEffect(() => {
    const lifetime = {
      context: changeContext,
      controller: new AbortController(),
      request: null as AbortController | null,
    };
    lifetimeRef.current = lifetime;
    void loadRunChanges();
    return () => {
      lifetime.controller.abort();
      lifetime.request?.abort();
    };
  }, [changeContext, loadRunChanges]);

  return loadRunChanges;
}
