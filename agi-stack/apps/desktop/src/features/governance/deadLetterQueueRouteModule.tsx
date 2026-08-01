import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { DeadLetterQueueScope } from './deadLetterQueueClient';
import type { DeadLetterQueueController } from './deadLetterQueueController';

const ROUTE_ID = 'tenant-tenant-dead-letter-queue' as const;
const LOCAL_POLICY = 'cloud_only' as const;
const noopRetry = (): void => {};

export type DeadLetterQueueRouteBinding = Readonly<{
  controller: DeadLetterQueueController;
  scope: DeadLetterQueueScope;
}>;

export type DeadLetterQueueRouteContext = Readonly<DesktopRouteContext & { tenantId: string }>;

export function createDeadLetterQueueRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: DeadLetterQueueRouteContext) => DeadLetterQueueRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('dead_letter_queue_route_binding_factory_invalid');
  }
  return async () => {
    const [{ DeadLetterQueuePage }, { useDeadLetterQueueController }] = await Promise.all([
      import('./DeadLetterQueuePage'),
      import('./useDeadLetterQueueController'),
    ]);

    function DeadLetterQueueRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <DeadLetterQueuePage
            model={unavailableModel(
              'cloud',
              'unavailable',
              'dead_letter_queue_route_context_unavailable',
            )}
            controller={inertController}
            onRetry={noopRetry}
          />
        );
      }
      return (
        <BoundDeadLetterQueueRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={DeadLetterQueuePage}
          useController={useDeadLetterQueueController}
        />
      );
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: ROUTE_ID,
      capability: ROUTE_ID,
      localPolicy: LOCAL_POLICY,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: DeadLetterQueueRouteSurface,
    });
    return module;
  };
}

function BoundDeadLetterQueueRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: DeadLetterQueueRouteContext;
  createBinding: (context: DeadLetterQueueRouteContext) => DeadLetterQueueRouteBinding;
  Page: typeof import('./DeadLetterQueuePage').DeadLetterQueuePage;
  useController: typeof import('./useDeadLetterQueueController').useDeadLetterQueueController;
}>) {
  const binding = useMemo(() => createBinding(context), [context.tenantId, createBinding]);
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <Page
        model={unavailableModel(
          binding.scope.authority,
          binding.scope.tenantId,
          'dead_letter_queue_route_binding_scope_mismatch',
        )}
        controller={inertController}
        onRetry={noopRetry}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return <Page model={model} controller={binding.controller} onRetry={retry} />;
}

function unavailableModel(
  authority: DeadLetterQueueScope['authority'],
  tenantId: string,
  reasonCode: string,
) {
  return Object.freeze({
    scope: Object.freeze({ authority, tenantId }),
    authority,
    messagesState: 'unavailable' as const,
    statsState: 'unavailable' as const,
    messagesReasonCode: reasonCode,
    statsReasonCode: reasonCode,
    mutationState: 'unavailable' as const,
    mutationReasonCode: reasonCode,
    retryMessagesVisible: false,
    retryStatsVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    messages: Object.freeze([]),
    stats: null,
    total: 0,
    limit: 50,
    offset: 0,
    hasMore: false,
    selectedIds: Object.freeze([]),
    detail: null,
    detailState: 'idle' as const,
    query: Object.freeze({
      status: 'all' as const,
      eventType: '',
      errorType: '',
      routingKey: '',
      limit: 50,
      offset: 0,
    }),
    lastUpdatedAt: null,
  });
}

const inertController: DeadLetterQueueController = Object.freeze({
  getSnapshot: () =>
    unavailableModel('cloud', 'unavailable', 'dead_letter_queue_route_context_unavailable'),
  subscribe: () => () => {},
  load: async () => {},
  retry: async () => {},
  retryMessage: async () => {},
  retryMessages: async () => {},
  retrySelected: async () => {},
  discardMessages: async () => {},
  discardMessage: async () => {},
  discardSelected: async () => {},
  cleanup: async () => {},
  setQuery: async () => {},
  openDetail: async () => {},
  closeDetail: () => {},
  toggleSelection: () => {},
  clearSelection: () => {},
  cancel: () => {},
  stop: () => {},
});

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
