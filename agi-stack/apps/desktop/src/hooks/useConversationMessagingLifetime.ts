import { useLayoutEffect, useMemo, useRef } from 'react';
import type { AgentConversationParams } from './useAgentConversation';

type Request = { controller: AbortController; conversations: Set<string | null> };

/** A send belongs to the rendered authority and selection, including before effects run. */
export function useConversationMessagingLifetime(params: AgentConversationParams) {
  const principalId = params.auth.user?.user_id ?? '';
  const cachedSession = params.agentConversationSession;
  // Local ordinary responses have no owner identity. This only records changes
  // observed by this mounted hook; it does not prove a cache's pre-mount origin.
  const cacheOrigin = useRef({
    principalId,
    session: cachedSession,
    rejected: null as AgentConversationParams['agentConversationSession'],
  });
  if (
    cacheOrigin.current.principalId !== principalId &&
    cacheOrigin.current.session === cachedSession
  ) {
    cacheOrigin.current.rejected = cachedSession;
  }
  if (cacheOrigin.current.session !== cachedSession || cachedSession === null) {
    cacheOrigin.current.rejected = null;
  }
  cacheOrigin.current.principalId = principalId;
  cacheOrigin.current.session = cachedSession;
  const configKey = JSON.stringify(params.config);
  const context = useMemo(
    () => ({
      requests: new Set<Request>(),
      mounted: false,
      latest: null as Request | null,
    }),
    [
      configKey,
      params.auth.user?.user_id,
      params.messagingOperationsV2,
      params.sessionRunInputOperationsV2,
      params.configScopeEpochRef.current,
      params.contextRevisionRef.current,
    ],
  );
  const current = useRef(params);
  const currentContext = useRef(context);
  current.current = params;
  currentContext.current = context;
  useLayoutEffect(() => {
    context.mounted = true;
    params.setSending(false);
    return () => {
      context.mounted = false;
      for (const request of context.requests) request.controller.abort();
      context.requests.clear();
    };
  }, [context]);
  const conversationId = params.selectedConversation?.id ?? null;
  useLayoutEffect(() => {
    for (const request of context.requests) {
      if (!request.conversations.has(conversationId)) {
        request.controller.abort();
        context.requests.delete(request);
      }
    }
    params.setSending(context.requests.size > 0);
  }, [context, conversationId]);

  return () => {
    if (
      !context.mounted ||
      currentContext.current !== context ||
      (current.current.selectedConversation?.id ?? null) !== conversationId
    )
      return null;
    const epoch = params.configScopeEpochRef.current;
    const revision = params.contextRevisionRef.current;
    let started = false;
    const request: Request = {
      controller: new AbortController(),
      conversations: new Set([conversationId]),
    };
    const isActive = () =>
      context.mounted &&
      currentContext.current === context &&
      !request.controller.signal.aborted &&
      params.configScopeEpochRef.current === epoch &&
      params.contextRevisionRef.current === revision &&
      request.conversations.has(current.current.selectedConversation?.id ?? null);
    const assertActive = () => {
      if (!isActive()) {
        request.controller.abort();
        throw new DOMException('Conversation messaging context released', 'AbortError');
      }
    };
    const guarded = <T extends (...args: any[]) => any>(callback: T): T =>
      ((...args: Parameters<T>) => {
        assertActive();
        // React may evaluate functional state updates after the originating request ended.
        const safeArgs =
          typeof args[0] === 'function'
            ? [(value: unknown) => (isActive() ? args[0](value) : value), ...args.slice(1)]
            : args;
        return callback(...safeArgs);
      }) as T;
    return {
      signal: request.controller.signal,
      isActive,
      assertActive,
      assertCachedSessionCurrent() {
        assertActive();
        if (cachedSession && cacheOrigin.current.rejected === cachedSession) {
          throw new Error('conversation_messaging_cached_principal_changed');
        }
      },
      adoptConversation(id: string) {
        assertActive();
        request.conversations.add(id);
      },
      start() {
        assertActive();
        started = true;
        context.requests.add(request);
        context.latest = request;
      },
      finish() {
        context.requests.delete(request);
        if (isActive()) params.setSending(context.requests.size > 0);
      },
      guardParams(value: AgentConversationParams): AgentConversationParams {
        return {
          ...value,
          setDataset: guarded(value.setDataset),
          setError: (error) => {
            assertActive();
            if (!started || context.latest === request) value.setError(error);
          },
          setSending: guarded(value.setSending),
          setRunInputReferences: guarded(value.setRunInputReferences),
          setRunInputs: guarded(value.setRunInputs),
          setAgentConversationSession: guarded(value.setAgentConversationSession),
          setConversationTimeline: guarded(value.setConversationTimeline),
          invalidateSessionAuthority: guarded(value.invalidateSessionAuthority),
          upsertAgentTaskSignal: guarded(value.upsertAgentTaskSignal),
          loadConversationTimeline: guarded(value.loadConversationTimeline),
        };
      },
    };
  };
}
