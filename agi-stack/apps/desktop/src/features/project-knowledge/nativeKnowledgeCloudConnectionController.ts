import type { NativeCloudAuthClient } from '../../api/nativeCloudAuthClient';
import type { NativeMemoriesAuthority } from './nativeMemoriesController';
import type { NativeKnowledgeClient, NativeKnowledgeScope } from './nativeKnowledgeContracts';
import type {
  NativeKnowledgeSyncConnection,
  NativeKnowledgeSyncTenant,
  NativeKnowledgeSyncProject,
  NativeKnowledgeSyncEnrollment,
} from './nativeKnowledgeDataGenerated';
import type {
  NativeKnowledgeCloudConnectionClient,
  NativeKnowledgeCloudConnectionCommand,
} from './nativeKnowledgeCloudConnectionClient';

export type NativeKnowledgeCloudConnectionModel = Readonly<{
  phase:
    | 'idle'
    | 'loading'
    | 'authenticating'
    | 'password_change_required'
    | 'disconnecting'
    | 'ready'
    | 'enrolling'
    | 'binding'
    | 'error';
  connection: NativeKnowledgeSyncConnection | null;
  tenants: readonly NativeKnowledgeSyncTenant[];
  projects: readonly NativeKnowledgeSyncProject[];
  selectedTenantId: string | null;
  selectedProjectId: string | null;
  enrollment: NativeKnowledgeSyncEnrollment | null;
  bound: boolean;
  error: 'failed' | 'contextChanged' | null;
}>;
export type NativeKnowledgeCloudConnectionController = ReturnType<
  typeof createNativeKnowledgeCloudConnectionController
>;

/** Cloud credentials remain in the native vault; this controller owns only observed selections. */
export function createNativeKnowledgeCloudConnectionController(
  input: Readonly<{
    client?: NativeKnowledgeCloudConnectionClient;
    sourceClient: NativeKnowledgeClient;
    authClient: NativeCloudAuthClient | null;
    authority: NativeMemoriesAuthority;
    onAccepted?: () => void;
  }>,
) {
  const initial = (): NativeKnowledgeCloudConnectionModel =>
    Object.freeze({
      phase: 'idle',
      connection: null,
      tenants: [],
      projects: [],
      selectedTenantId: null,
      selectedProjectId: null,
      enrollment: null,
      bound: false,
      error: null,
    });
  let model = initial();
  let active = true;
  let revision = 0;
  let pending: AbortController | null = null;
  let observed: NativeKnowledgeScope | null = null;
  let authenticationPending = false;
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeKnowledgeCloudConnectionModel>) => {
    model = Object.freeze({ ...model, ...patch });
    for (const listener of [...listeners]) listener();
  };
  const available = () =>
    active &&
    input.authority.available &&
    input.authority.scope.authority === 'local' &&
    input.authority.userId !== null &&
    input.authority.sessionId !== null &&
    input.authority.generationDigest !== null &&
    input.authority.allowedActions.includes('sync_status') &&
    Boolean(input.client);
  const begin = (phase: NativeKnowledgeCloudConnectionModel['phase']) => {
    pending?.abort();
    pending = new AbortController();
    revision += 1;
    emit({ phase, error: null });
    return { revision, signal: pending.signal };
  };
  type Request = ReturnType<typeof begin>;
  const current = (request: Request) =>
    available() && request.revision === revision && !request.signal.aborted;
  const requireCurrent = (request: Request) => {
    if (!current(request)) throw new Error('knowledge_scope_mismatch');
  };
  const fail = (request: Request, error: unknown) => {
    if (!current(request)) return;
    const message = error instanceof Error ? error.message : '';
    const errorCode = [
      'knowledge_scope_mismatch',
      'knowledge_generation_mismatch',
      'project_knowledge_scope_conflict',
      'cloud_auth_attempt_retired',
    ].includes(message)
      ? 'contextChanged'
      : 'failed';
    emit({ phase: 'error', error: errorCode, bound: false });
  };
  const observe = async (request: Request) => {
    requireCurrent(request);
    if (!input.sourceClient.observeScope) throw new Error('knowledge_scope_mismatch');
    const scope = await input.sourceClient.observeScope(input.authority.scope, {
      expectedActorId: input.authority.userId!,
      signal: request.signal,
    });
    requireCurrent(request);
    if (
      scope.tenant_id !== input.authority.scope.tenantId ||
      scope.project_id !== input.authority.scope.projectId ||
      scope.context_revision !== input.authority.contextRevision ||
      scope.digest !== input.authority.generationDigest
    )
      throw new Error('knowledge_scope_mismatch');
    observed = scope;
  };
  const execute = async <C extends NativeKnowledgeCloudConnectionCommand>(
    command: C,
    request: Request,
  ) => {
    requireCurrent(request);
    if (!observed || !input.client) throw new Error('knowledge_scope_mismatch');
    const response = await input.client.execute(input.authority.scope, command, {
      expectedScope: observed,
      signal: request.signal,
    });
    requireCurrent(request);
    return response.result;
  };
  const loadConnection = async (request: Request) => {
    observed = null;
    await observe(request);
    const { connection } = await execute({ operation: 'connection' }, request);
    if (!connection) {
      emit({ ...initial(), phase: 'ready' });
      return;
    }
    const result = await execute(
      {
        operation: 'tenants',
        expected_connection_revision: connection.connection_revision,
      },
      request,
    );
    emit({
      ...initial(),
      phase: 'ready',
      connection: result.connection,
      tenants: result.items,
    });
  };
  const refresh = async () => {
    if (!available() || authenticationPending) return;
    const request = begin('loading');
    emit({ bound: false });
    try {
      const authStatus = await input.authClient?.getStatus();
      requireCurrent(request);
      if (authStatus?.status === 'password_change_required') {
        emit({ ...initial(), phase: 'password_change_required' });
        return;
      }
      await loadConnection(request);
    } catch (error) {
      fail(request, error);
    }
  };
  const login = async (credentials: Parameters<NativeCloudAuthClient['loginWithPassword']>[0]) => {
    if (!available() || !input.authClient) return;
    const request = begin('authenticating');
    emit({
      connection: null,
      tenants: [],
      projects: [],
      selectedTenantId: null,
      selectedProjectId: null,
      enrollment: null,
      bound: false,
    });
    authenticationPending = true;
    try {
      const result = await input.authClient.loginWithPassword(credentials);
      requireCurrent(request);
      if (result.status === 'password_change_required') emit({ phase: 'password_change_required' });
      else await loadConnection(request);
    } catch (error) {
      fail(request, error);
    } finally {
      if (request.revision === revision) authenticationPending = false;
    }
  };
  const changePassword = async (
    credentials: Parameters<NativeCloudAuthClient['forceChangePassword']>[0],
  ) => {
    if (!available() || !input.authClient || model.phase !== 'password_change_required') return;
    const request = begin('authenticating');
    authenticationPending = true;
    try {
      await input.authClient.forceChangePassword(credentials);
      requireCurrent(request);
      await loadConnection(request);
    } catch (error) {
      if (current(request)) emit({ phase: 'password_change_required', error: 'failed' });
    } finally {
      if (request.revision === revision) authenticationPending = false;
    }
  };
  const disconnect = async () => {
    if (!available() || !input.authClient) return;
    const request = begin('disconnecting');
    authenticationPending = false;
    observed = null;
    emit({
      connection: null,
      tenants: [],
      projects: [],
      selectedTenantId: null,
      selectedProjectId: null,
      enrollment: null,
      bound: false,
    });
    try {
      await input.authClient.signOut();
      requireCurrent(request);
      emit({ phase: 'ready' });
      input.onAccepted?.();
    } catch (error) {
      fail(request, error);
    }
  };
  const selectTenant = async (id: string) => {
    if (!available() || !model.connection || !model.tenants.some((tenant) => tenant.id === id))
      return;
    const connection = model.connection;
    const request = begin('loading');
    emit({
      selectedTenantId: id,
      selectedProjectId: null,
      projects: [],
      enrollment: null,
      bound: false,
    });
    try {
      const result = await execute(
        {
          operation: 'projects',
          tenant_id: id,
          expected_connection_revision: connection.connection_revision,
        },
        request,
      );
      emit({
        phase: 'ready',
        connection: result.connection,
        projects: result.items,
      });
    } catch (error) {
      fail(request, error);
    }
  };
  const selectProject = async (id: string) => {
    if (
      !available() ||
      !model.connection ||
      !model.selectedTenantId ||
      !model.projects.some(
        (project) => project.id === id && project.tenant_id === model.selectedTenantId,
      )
    )
      return;
    const connection = model.connection;
    const tenantId = model.selectedTenantId;
    const request = begin('loading');
    emit({ selectedProjectId: id, enrollment: null, bound: false });
    try {
      const result = await execute(
        {
          operation: 'enrollment',
          tenant_id: tenantId,
          project_id: id,
          expected_connection_revision: connection.connection_revision,
        },
        request,
      );
      emit({
        phase: 'ready',
        connection: result.connection,
        enrollment: result.enrollment,
      });
    } catch (error) {
      fail(request, error);
    }
  };
  const target = async (operation: 'enroll' | 'bind') => {
    if (
      !available() ||
      !model.connection ||
      !model.enrollment ||
      !model.selectedTenantId ||
      !model.selectedProjectId ||
      model.phase !== 'ready' ||
      (operation === 'enroll'
        ? model.enrollment.enabled || !model.enrollment.can_enroll
        : !model.enrollment.enabled)
    )
      return;
    const { connection, enrollment, selectedTenantId, selectedProjectId } = model;
    const request = begin(operation === 'enroll' ? 'enrolling' : 'binding');
    emit({ bound: false });
    try {
      const result = await execute(
        {
          operation,
          tenant_id: selectedTenantId,
          project_id: selectedProjectId,
          expected_connection_revision: connection.connection_revision,
          expected_generation: enrollment.generation,
        },
        request,
      );
      emit({
        phase: 'ready',
        connection: result.connection,
        enrollment: result.enrollment,
        bound:
          operation === 'bind' &&
          'association_state' in result &&
          result.association_state === 'verified',
      });
      input.onAccepted?.();
    } catch (error) {
      fail(request, error);
    }
  };
  return Object.freeze({
    getSnapshot: () => model,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    activate: () => {
      active = true;
    },
    stop: () => {
      active = false;
      revision += 1;
      pending?.abort();
      observed = null;
      // The host retires authentication on local authority exit. Renderer owner retirement
      // during a cloud vault write must not cancel that same authorized authentication.
      authenticationPending = false;
      model = initial();
    },
    refresh,
    login,
    changePassword,
    disconnect,
    selectTenant,
    selectProject,
    enroll: () => target('enroll'),
    bind: () => target('bind'),
  });
}
