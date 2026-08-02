import { DesktopApiError } from '../../api/client';
import { RUNTIME_DEPLOYMENTS_CLOUD_ACTIONS } from './runtimeDeploymentsCapability';
import { RuntimeDeploymentsUnavailableError } from './runtimeDeploymentsClient';
import type {
  RuntimeDeployment,
  RuntimeDeploymentDetailState,
  RuntimeDeploymentProgressEvent,
  RuntimeDeploymentProgressState,
  RuntimeDeploymentsAuthority,
  RuntimeDeploymentsClient,
  RuntimeDeploymentsModel,
  RuntimeDeploymentsNormalizedQuery,
  RuntimeDeploymentsPage,
  RuntimeDeploymentsQuery,
  RuntimeDeploymentsResourceState,
  RuntimeDeploymentsScope,
} from './runtimeDeploymentsTypes';

export type RuntimeDeploymentsController = Readonly<{
  getSnapshot(): RuntimeDeploymentsModel;
  subscribe(listener: () => void): () => void;
  load(
    scope: RuntimeDeploymentsScope,
    query?: RuntimeDeploymentsQuery,
  ): Promise<void>;
  retry(): Promise<void>;
  setQuery(query: RuntimeDeploymentsQuery): Promise<void>;
  inspect(deploymentId: string): Promise<void>;
  closeDetail(): void;
  reconnectProgress(): Promise<void>;
  cancel(): void;
  stop(): void;
}>;

const DEFAULT_QUERY: RuntimeDeploymentsNormalizedQuery = Object.freeze({
  page: 1,
  pageSize: 10,
});

export function createRuntimeDeploymentsController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: RuntimeDeploymentsAuthority;
  client: RuntimeDeploymentsClient;
  initialScope: RuntimeDeploymentsScope;
}>): RuntimeDeploymentsController {
  let activeScope = freezeScope(initialScope);
  let activeQuery = DEFAULT_QUERY;
  let model =
    authority === 'local'
      ? unavailableModel(activeScope, activeQuery)
      : loadingModel(activeScope, activeQuery);
  let listController: AbortController | null = null;
  let detailController: AbortController | null = null;
  let progressController: AbortController | null = null;
  let listRevision = 0;
  let detailRevision = 0;
  let progressRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: RuntimeDeploymentsModel): void => {
    model = Object.freeze(next);
    for (const listener of [...listeners]) listener();
  };
  const cancelList = (): void => {
    listRevision += 1;
    listController?.abort();
    listController = null;
  };
  const cancelDetail = (): void => {
    detailRevision += 1;
    detailController?.abort();
    detailController = null;
  };
  const cancelProgress = (): void => {
    progressRevision += 1;
    progressController?.abort();
    progressController = null;
  };
  const cancel = (): void => {
    cancelList();
    cancelDetail();
    cancelProgress();
  };
  const load = async (
    nextScope: RuntimeDeploymentsScope,
    query: RuntimeDeploymentsQuery = activeQuery,
  ): Promise<void> => {
    const scope = freezeScope(nextScope);
    const normalizedQuery = normalizeQuery(query);
    const scopeChanged = !sameScope(activeScope, scope);
    activeScope = scope;
    activeQuery = normalizedQuery;
    if (scopeChanged) {
      cancelDetail();
      cancelProgress();
    }
    if (scope.authority !== authority) {
      cancel();
      emit(
        unavailableModel(
          scope,
          normalizedQuery,
          'runtime_deployments_controller_authority_mismatch',
        ),
      );
      return;
    }
    if (scope.authority === 'local') {
      cancel();
      emit(unavailableModel(scope, normalizedQuery));
      return;
    }
    if (scope.instanceId === null) {
      cancel();
      emit(
        unavailableModel(
          scope,
          normalizedQuery,
          'runtime_deployments_instance_scope_required',
        ),
      );
      return;
    }

    const stable = model;
    const revision = ++listRevision;
    listController?.abort();
    const controller = new AbortController();
    listController = controller;
    emit({
      ...stable,
      scope,
      authority,
      state: 'loading',
      reasonCode: cloudReasonCode(),
      retryVisible: false,
      query: normalizedQuery,
      ...(scopeChanged
        ? {
            selectedDeployment: null,
            detailState: 'idle' as const,
            detailReasonCode: null,
            progressState: 'idle' as const,
            progressReasonCode: null,
            progressRetryVisible: false,
          }
        : {}),
    });
    try {
      const page = await client.list(scope, normalizedQuery, {
        signal: controller.signal,
      });
      if (!listRequestIsCurrent(revision, controller)) return;
      listController = null;
      emit(loadedModel(scope, normalizedQuery, page, model));
    } catch (error) {
      if (!listRequestIsCurrent(revision, controller)) return;
      listController = null;
      emit(loadErrorModel(stable, scope, normalizedQuery, error));
    }
  };
  const inspect = async (deploymentId: string): Promise<void> => {
    if (authority !== 'cloud') {
      throw new RuntimeDeploymentsUnavailableError(
        'cloud_deployment_authority_not_applicable',
      );
    }
    const id = listedDeployment(model.deployments, deploymentId).id;
    cancelDetail();
    cancelProgress();
    const revision = ++detailRevision;
    const controller = new AbortController();
    detailController = controller;
    emit({
      ...model,
      selectedDeployment: null,
      detailState: 'loading',
      detailReasonCode: null,
      progressState: 'idle',
      progressReasonCode: null,
      progressRetryVisible: false,
    });
    try {
      const deployment = await client.get(activeScope, id, {
        signal: controller.signal,
      });
      if (!detailRequestIsCurrent(revision, controller)) return;
      detailController = null;
      emit({
        ...model,
        selectedDeployment: deployment,
        detailState: 'ready',
        detailReasonCode: null,
      });
      if (terminal(deployment.status)) {
        emit({
          ...model,
          progressState: 'complete',
          progressReasonCode: null,
          progressRetryVisible: false,
        });
        return;
      }
      startProgress(id);
      await Promise.resolve();
    } catch (error) {
      if (!detailRequestIsCurrent(revision, controller)) return;
      detailController = null;
      const classified = classifyError(
        error,
        'runtime_deployments_detail_failed',
      );
      emit({
        ...model,
        selectedDeployment: null,
        detailState: detailState(classified.resourceState),
        detailReasonCode: classified.reasonCode,
        progressState: 'idle',
        progressReasonCode: null,
        progressRetryVisible: false,
      });
    }
  };
  const startProgress = (deploymentId: string): void => {
    const revision = ++progressRevision;
    progressController?.abort();
    const controller = new AbortController();
    progressController = controller;
    emit({
      ...model,
      progressState: 'connecting',
      progressReasonCode: null,
      progressRetryVisible: false,
    });
    const stream = client.streamProgress(
      activeScope,
      deploymentId,
      (event) => refreshDetailFromProgress(revision, controller, event),
      { signal: controller.signal },
    );
    emit({
      ...model,
      progressState: 'connected',
      progressReasonCode: null,
      progressRetryVisible: false,
    });
    void stream.catch((error: unknown) => {
      if (!progressRequestIsCurrent(revision, controller)) return;
      progressController = null;
      const classified = classifyError(
        error,
        'runtime_deployments_progress_disconnected',
      );
      emit({
        ...model,
        progressState: progressState(classified.resourceState),
        progressReasonCode: classified.reasonCode,
        progressRetryVisible: true,
      });
    });
  };
  const refreshDetailFromProgress = async (
    revision: number,
    controller: AbortController,
    event: RuntimeDeploymentProgressEvent,
  ): Promise<void> => {
    const selected = model.selectedDeployment;
    if (
      !selected ||
      !progressRequestIsCurrent(revision, controller) ||
      (event.deployId !== null && event.deployId !== selected.id)
    ) {
      return;
    }
    try {
      const deployment = await client.get(activeScope, selected.id, {
        signal: controller.signal,
      });
      if (!progressRequestIsCurrent(revision, controller)) return;
      const isComplete = event.type === 'done' || terminal(deployment.status);
      if (isComplete) {
        progressController = null;
      }
      emit({
        ...model,
        selectedDeployment: deployment,
        detailState: 'ready',
        detailReasonCode: null,
        progressState: isComplete ? 'complete' : 'connected',
        progressReasonCode: null,
        progressRetryVisible: false,
      });
    } catch (error) {
      if (!progressRequestIsCurrent(revision, controller)) return;
      const classified = classifyError(
        error,
        'runtime_deployments_progress_refresh_failed',
      );
      emit({
        ...model,
        progressState: progressState(classified.resourceState),
        progressReasonCode: classified.reasonCode,
        progressRetryVisible: true,
      });
    }
  };

  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    load,
    retry: () => load(activeScope, activeQuery),
    setQuery: (query) => load(activeScope, { ...activeQuery, ...query }),
    inspect,
    closeDetail() {
      cancelDetail();
      cancelProgress();
      emit({
        ...model,
        selectedDeployment: null,
        detailState: 'idle',
        detailReasonCode: null,
        progressState: 'idle',
        progressReasonCode: null,
        progressRetryVisible: false,
      });
    },
    async reconnectProgress() {
      const selected = model.selectedDeployment;
      if (!selected || terminal(selected.status)) return;
      await inspect(selected.id);
    },
    cancel,
    stop: cancel,
  });

  function listRequestIsCurrent(
    revision: number,
    controller: AbortController,
  ): boolean {
    return (
      revision === listRevision &&
      listController === controller &&
      !controller.signal.aborted
    );
  }

  function detailRequestIsCurrent(
    revision: number,
    controller: AbortController,
  ): boolean {
    return (
      revision === detailRevision &&
      detailController === controller &&
      !controller.signal.aborted
    );
  }

  function progressRequestIsCurrent(
    revision: number,
    controller: AbortController,
  ): boolean {
    return (
      revision === progressRevision &&
      progressController === controller &&
      !controller.signal.aborted
    );
  }
}

function loadingModel(
  scope: RuntimeDeploymentsScope,
  query: RuntimeDeploymentsNormalizedQuery,
): RuntimeDeploymentsModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: 'loading',
    reasonCode: cloudReasonCode(),
    retryVisible: false,
    allowedActions: RUNTIME_DEPLOYMENTS_CLOUD_ACTIONS,
    deployments: Object.freeze([]),
    total: 0,
    query,
    selectedDeployment: null,
    detailState: 'idle',
    detailReasonCode: null,
    progressState: 'idle',
    progressReasonCode: null,
    progressRetryVisible: false,
    lastUpdatedAt: null,
  });
}

function unavailableModel(
  scope: RuntimeDeploymentsScope,
  query: RuntimeDeploymentsNormalizedQuery,
  reasonCode = 'cloud_deployment_authority_not_applicable',
): RuntimeDeploymentsModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: 'unavailable',
    reasonCode,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    deployments: Object.freeze([]),
    total: 0,
    query,
    selectedDeployment: null,
    detailState: 'unavailable',
    detailReasonCode: reasonCode,
    progressState: 'unavailable',
    progressReasonCode: reasonCode,
    progressRetryVisible: false,
    lastUpdatedAt: null,
  });
}

function loadedModel(
  scope: RuntimeDeploymentsScope,
  query: RuntimeDeploymentsNormalizedQuery,
  page: RuntimeDeploymentsPage,
  current: RuntimeDeploymentsModel,
): RuntimeDeploymentsModel {
  return Object.freeze({
    ...current,
    scope,
    authority: scope.authority,
    state: page.deployments.length === 0 ? 'empty' : 'ready',
    reasonCode: cloudReasonCode(),
    retryVisible: false,
    allowedActions: RUNTIME_DEPLOYMENTS_CLOUD_ACTIONS,
    deployments: page.deployments,
    total: page.total,
    query: Object.freeze({ page: page.page, pageSize: page.pageSize }),
    lastUpdatedAt: new Date().toISOString(),
  });
}

function loadErrorModel(
  stable: RuntimeDeploymentsModel,
  scope: RuntimeDeploymentsScope,
  query: RuntimeDeploymentsNormalizedQuery,
  error: unknown,
): RuntimeDeploymentsModel {
  const classified = classifyError(error, 'runtime_deployments_load_failed');
  const hasStableData = stable.deployments.length > 0;
  return Object.freeze({
    ...stable,
    scope,
    authority: scope.authority,
    state: hasStableData ? 'stale' : classified.resourceState,
    reasonCode: classified.reasonCode,
    retryVisible: true,
    query,
  });
}

function classifyError(
  error: unknown,
  fallback: string,
): Readonly<{
  resourceState: RuntimeDeploymentsResourceState;
  reasonCode: string;
}> {
  if (error instanceof RuntimeDeploymentsUnavailableError) {
    return Object.freeze({
      resourceState: 'unavailable',
      reasonCode: error.reasonCode,
    });
  }
  if (error instanceof DesktopApiError) {
    if (error.status === 403) {
      return Object.freeze({
        resourceState: 'forbidden',
        reasonCode: 'runtime_deployments_forbidden',
      });
    }
    if (error.status === 409) {
      return Object.freeze({
        resourceState: 'conflict',
        reasonCode: 'runtime_deployments_conflict',
      });
    }
  }
  return Object.freeze({ resourceState: 'error', reasonCode: fallback });
}

function detailState(
  state: RuntimeDeploymentsResourceState,
): RuntimeDeploymentDetailState {
  if (
    state === 'forbidden' ||
    state === 'conflict' ||
    state === 'unavailable'
  ) {
    return state;
  }
  return 'error';
}

function progressState(
  state: RuntimeDeploymentsResourceState,
): RuntimeDeploymentProgressState {
  return state === 'unavailable' ? 'unavailable' : 'stale';
}

function listedDeployment(
  deployments: readonly RuntimeDeployment[],
  deploymentId: string,
): RuntimeDeployment {
  const deployment = deployments.find(
    (candidate) => candidate.id === deploymentId,
  );
  if (!deployment) {
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_selection_invalid',
    );
  }
  return deployment;
}

function normalizeQuery(
  query: RuntimeDeploymentsQuery,
): RuntimeDeploymentsNormalizedQuery {
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 10;
  if (
    !Number.isInteger(page) ||
    page < 1 ||
    !Number.isInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > 100
  ) {
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_query_invalid',
    );
  }
  return Object.freeze({ page, pageSize });
}

function freezeScope(
  scope: RuntimeDeploymentsScope,
): RuntimeDeploymentsScope {
  if (!scope.tenantId || scope.tenantId !== scope.tenantId.trim()) {
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_scope_invalid',
    );
  }
  if (
    scope.instanceId !== null &&
    (!scope.instanceId || scope.instanceId !== scope.instanceId.trim())
  ) {
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_scope_invalid',
    );
  }
  return Object.freeze({ ...scope });
}

function sameScope(
  left: RuntimeDeploymentsScope,
  right: RuntimeDeploymentsScope,
): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.instanceId === right.instanceId
  );
}

function terminal(status: RuntimeDeployment['status']): boolean {
  return status === 'success' || status === 'failed' || status === 'cancelled';
}

function cloudReasonCode(): string {
  return 'runtime_deployments_mutations_and_instance_discovery_partial';
}
