import { DesktopApiError } from '../../api/client';
import { INSTANCE_TEMPLATES_CLOUD_ACTIONS } from './instanceTemplatesCapability';
import { InstanceTemplatesUnavailableError } from './instanceTemplatesClient';
import type {
  InstanceTemplateCreateInput,
  InstanceTemplateSummary,
  InstanceTemplatesAuthority,
  InstanceTemplatesClient,
  InstanceTemplatesDetailState,
  InstanceTemplatesModel,
  InstanceTemplatesMutationState,
  InstanceTemplatesNormalizedQuery,
  InstanceTemplatesPage,
  InstanceTemplatesQuery,
  InstanceTemplatesResourceState,
  InstanceTemplatesScope,
} from './instanceTemplatesTypes';

export type InstanceTemplatesController = Readonly<{
  getSnapshot(): InstanceTemplatesModel;
  subscribe(listener: () => void): () => void;
  load(scope: InstanceTemplatesScope, query?: InstanceTemplatesQuery): Promise<void>;
  retry(): Promise<void>;
  setQuery(query: InstanceTemplatesQuery): Promise<void>;
  setFilters(query: InstanceTemplatesQuery): void;
  inspect(templateId: string): Promise<void>;
  closeDetail(): void;
  create(input: InstanceTemplateCreateInput): Promise<void>;
  delete(templateId: string): Promise<void>;
  publish(templateId: string): Promise<void>;
  clone(templateId: string, newName: string): Promise<void>;
  cancel(): void;
  stop(): void;
}>;

const DEFAULT_QUERY: InstanceTemplatesNormalizedQuery = Object.freeze({
  page: 1,
  pageSize: 20,
  search: '',
  status: 'all',
});

export function createInstanceTemplatesController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: InstanceTemplatesAuthority;
  client: InstanceTemplatesClient;
  initialScope: InstanceTemplatesScope;
}>): InstanceTemplatesController {
  let activeScope = freezeScope(initialScope);
  let activeQuery = DEFAULT_QUERY;
  let model =
    authority === 'local'
      ? unavailableModel(activeScope, activeQuery)
      : loadingModel(activeScope, activeQuery);
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: InstanceTemplatesModel): void => {
    model = Object.freeze(next);
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const beginRequest = (): Readonly<{
    revision: number;
    controller: AbortController;
  }> => {
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    return Object.freeze({ revision, controller });
  };
  const isCurrent = (
    revision: number,
    controller: AbortController,
  ): boolean =>
    revision === requestRevision &&
    requestController === controller &&
    !controller.signal.aborted;

  const load = async (
    nextScope: InstanceTemplatesScope,
    query: InstanceTemplatesQuery = activeQuery,
  ): Promise<void> => {
    const scope = freezeScope(nextScope);
    const normalizedQuery = normalizeQuery(query);
    activeScope = scope;
    activeQuery = normalizedQuery;
    if (scope.authority !== authority) {
      cancel();
      emit(
        unavailableModel(
          scope,
          normalizedQuery,
          'instance_templates_controller_authority_mismatch',
        ),
      );
      return;
    }
    if (scope.authority === 'local') {
      cancel();
      emit(unavailableModel(scope, normalizedQuery));
      return;
    }

    const stable = model;
    const { revision, controller } = beginRequest();
    emit({
      ...stable,
      scope,
      authority,
      state: 'loading',
      reasonCode: cloudReasonCode(),
      retryVisible: false,
      query: normalizedQuery,
      detailState: 'idle',
      detailReasonCode: null,
      selectedTemplate: null,
      items: Object.freeze([]),
      mutationState: 'idle',
      mutationReasonCode: null,
    });
    try {
      const page = await client.list(scope, normalizedQuery, {
        signal: controller.signal,
      });
      if (!isCurrent(revision, controller)) return;
      requestController = null;
      emit(loadedModel(scope, normalizedQuery, page));
    } catch (error) {
      if (!isCurrent(revision, controller)) return;
      requestController = null;
      emit(loadErrorModel(stable, scope, normalizedQuery, error));
    }
  };

  const inspect = async (templateId: string): Promise<void> => {
    requireCloudAuthority(activeScope);
    const id = exactIdentifier(templateId);
    const { revision, controller } = beginRequest();
    emit({
      ...model,
      selectedTemplate: null,
      detailState: 'loading',
      detailReasonCode: null,
      items: Object.freeze([]),
    });
    try {
      const [template, items] = await Promise.all([
        client.get(activeScope, id, { signal: controller.signal }),
        client.listItems(activeScope, id, { signal: controller.signal }),
      ]);
      if (!isCurrent(revision, controller)) return;
      requestController = null;
      emit({
        ...model,
        selectedTemplate: template,
        detailState: 'ready',
        detailReasonCode: null,
        items,
      });
    } catch (error) {
      if (!isCurrent(revision, controller)) throw error;
      requestController = null;
      const classified = classifyError(error, 'instance_templates_detail_failed');
      emit({
        ...model,
        selectedTemplate: null,
        detailState: detailState(classified.resourceState),
        detailReasonCode: classified.reasonCode,
        items: Object.freeze([]),
      });
      throw error;
    }
  };

  const mutate = async (
    operation: (signal: AbortSignal) => Promise<unknown>,
  ): Promise<void> => {
    requireCloudAuthority(activeScope);
    const { revision, controller } = beginRequest();
    emit({
      ...model,
      mutationState: 'submitting',
      mutationReasonCode: null,
    });
    try {
      await operation(controller.signal);
      if (!isCurrent(revision, controller)) return;
      requestController = null;
      emit({
        ...model,
        mutationState: 'idle',
        mutationReasonCode: null,
      });
      await load(activeScope, activeQuery);
    } catch (error) {
      if (!isCurrent(revision, controller)) throw error;
      requestController = null;
      const classified = classifyError(error, 'instance_templates_mutation_failed');
      emit({
        ...model,
        mutationState: mutationState(classified.resourceState),
        mutationReasonCode: classified.reasonCode,
      });
      throw error;
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
    setFilters(query) {
      activeQuery = normalizeQuery({ ...activeQuery, ...query });
      emit({
        ...model,
        query: activeQuery,
        visibleTemplates: visibleTemplates(model.templates, activeQuery),
      });
    },
    inspect,
    closeDetail() {
      cancel();
      emit({
        ...model,
        selectedTemplate: null,
        detailState: 'idle',
        detailReasonCode: null,
        items: Object.freeze([]),
      });
    },
    create: (input) =>
      mutate((signal) => client.create(activeScope, input, { signal })),
    delete: (templateId) =>
      mutate((signal) =>
        client.delete(activeScope, exactIdentifier(templateId), { signal }),
      ),
    publish: (templateId) =>
      mutate((signal) =>
        client.publish(activeScope, exactIdentifier(templateId), { signal }),
      ),
    clone: (templateId, newName) =>
      mutate((signal) =>
        client.clone(
          activeScope,
          exactIdentifier(templateId),
          exactIdentifier(newName),
          { signal },
        ),
      ),
    cancel,
    stop: cancel,
  });
}

function loadingModel(
  scope: InstanceTemplatesScope,
  query: InstanceTemplatesNormalizedQuery,
): InstanceTemplatesModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: 'loading',
    reasonCode: cloudReasonCode(),
    retryVisible: false,
    allowedActions: INSTANCE_TEMPLATES_CLOUD_ACTIONS,
    templates: Object.freeze([]),
    visibleTemplates: Object.freeze([]),
    total: 0,
    query,
    selectedTemplate: null,
    detailState: 'idle',
    detailReasonCode: null,
    items: Object.freeze([]),
    mutationState: 'idle',
    mutationReasonCode: null,
    lastUpdatedAt: null,
  });
}

function unavailableModel(
  scope: InstanceTemplatesScope,
  query: InstanceTemplatesNormalizedQuery,
  reasonCode = 'local_instance_template_authority_unavailable',
): InstanceTemplatesModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: 'unavailable',
    reasonCode,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    templates: Object.freeze([]),
    visibleTemplates: Object.freeze([]),
    total: 0,
    query,
    selectedTemplate: null,
    detailState: 'unavailable',
    detailReasonCode: reasonCode,
    items: Object.freeze([]),
    mutationState: 'unavailable',
    mutationReasonCode: reasonCode,
    lastUpdatedAt: null,
  });
}

function loadedModel(
  scope: InstanceTemplatesScope,
  query: InstanceTemplatesNormalizedQuery,
  page: InstanceTemplatesPage,
): InstanceTemplatesModel {
  const normalized = Object.freeze({
    ...query,
    page: page.page,
    pageSize: page.pageSize,
  });
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: page.templates.length === 0 ? 'empty' : 'ready',
    reasonCode: cloudReasonCode(),
    retryVisible: false,
    allowedActions: INSTANCE_TEMPLATES_CLOUD_ACTIONS,
    templates: page.templates,
    visibleTemplates: visibleTemplates(page.templates, normalized),
    total: page.total,
    query: normalized,
    selectedTemplate: null,
    detailState: 'idle',
    detailReasonCode: null,
    items: Object.freeze([]),
    mutationState: 'idle',
    mutationReasonCode: null,
    lastUpdatedAt: new Date().toISOString(),
  });
}

function loadErrorModel(
  stable: InstanceTemplatesModel,
  scope: InstanceTemplatesScope,
  query: InstanceTemplatesNormalizedQuery,
  error: unknown,
): InstanceTemplatesModel {
  const classified = classifyError(error, 'instance_templates_load_failed');
  const hasStableRows =
    stable.scope.authority === scope.authority &&
    stable.scope.tenantId === scope.tenantId &&
    stable.templates.length > 0;
  const templates = hasStableRows ? stable.templates : Object.freeze([]);
  return Object.freeze({
    ...stable,
    scope,
    authority: scope.authority,
    state: hasStableRows ? 'stale' : classified.resourceState,
    reasonCode: hasStableRows
      ? 'instance_templates_load_failed'
      : classified.reasonCode,
    retryVisible: true,
    templates,
    visibleTemplates: visibleTemplates(templates, query),
    total: hasStableRows ? stable.total : 0,
    query,
    selectedTemplate: null,
    detailState: 'idle',
    detailReasonCode: null,
    items: Object.freeze([]),
    mutationState: 'idle',
    mutationReasonCode: null,
  });
}

function visibleTemplates(
  templates: readonly InstanceTemplateSummary[],
  query: InstanceTemplatesNormalizedQuery,
): readonly InstanceTemplateSummary[] {
  const search = query.search.toLocaleLowerCase();
  return Object.freeze(
    templates.filter((template) => {
      if (query.status === 'published' && !template.isPublished) return false;
      if (query.status === 'draft' && template.isPublished) return false;
      if (!search) return true;
      return `${template.name} ${template.description ?? ''} ${template.slug}`
        .toLocaleLowerCase()
        .includes(search);
    }),
  );
}

function normalizeQuery(
  query: InstanceTemplatesQuery,
): InstanceTemplatesNormalizedQuery {
  const page = positiveInteger(query.page, 1);
  const pageSize = positiveInteger(query.pageSize, 20);
  const status =
    query.status === 'published' || query.status === 'draft'
      ? query.status
      : query.isPublished === true
        ? 'published'
        : query.isPublished === false
          ? 'draft'
          : 'all';
  return Object.freeze({
    page,
    pageSize,
    search: (query.search ?? '').trim(),
    status,
  });
}

function positiveInteger(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isSafeInteger(value) && value > 0
    ? value
    : fallback;
}

function freezeScope(scope: InstanceTemplatesScope): InstanceTemplatesScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: exactIdentifier(scope.tenantId),
  });
}

function exactIdentifier(value: string): string {
  if (!value || value !== value.trim()) {
    throw new InstanceTemplatesUnavailableError(
      'instance_templates_identifier_invalid',
    );
  }
  return value;
}

function requireCloudAuthority(scope: InstanceTemplatesScope): void {
  if (scope.authority !== 'cloud') {
    throw new InstanceTemplatesUnavailableError(
      'local_instance_template_authority_unavailable',
    );
  }
}

function cloudReasonCode(): string {
  return 'instance_templates_nested_deep_link_and_deploy_partial';
}

function classifyError(
  error: unknown,
  fallback: string,
): Readonly<{
  resourceState: InstanceTemplatesResourceState;
  reasonCode: string;
}> {
  if (error instanceof InstanceTemplatesUnavailableError) {
    return Object.freeze({
      resourceState: 'unavailable',
      reasonCode: error.reasonCode,
    });
  }
  if (error instanceof DesktopApiError) {
    if (error.status === 403) {
      return Object.freeze({
        resourceState: 'forbidden',
        reasonCode: 'instance_templates_forbidden',
      });
    }
    if (error.status === 409) {
      return Object.freeze({
        resourceState: 'conflict',
        reasonCode: 'instance_templates_conflict',
      });
    }
  }
  return Object.freeze({ resourceState: 'error', reasonCode: fallback });
}

function detailState(
  state: InstanceTemplatesResourceState,
): InstanceTemplatesDetailState {
  return state === 'stale' || state === 'empty' ? 'error' : state;
}

function mutationState(
  state: InstanceTemplatesResourceState,
): InstanceTemplatesMutationState {
  return state === 'stale' || state === 'empty' || state === 'loading'
    ? 'error'
    : state === 'ready'
      ? 'idle'
      : state;
}
