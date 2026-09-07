import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import { createLocalStorageActivityReadRetryStore } from '../features/agent-authority/activityReadRetryStore';
import { parseActivityReadState } from '../features/agent-authority/agentAuthorityContract';
import type {
  ActivityReadRetryStore,
  ActivityReadUpdateResult,
  UpdateActivityReadStateRequest,
} from '../features/agent-authority/agentAuthorityTypes';
import {
  activityReadStateErrorV2,
  activityReadStateRecordV2,
  checkActivityReadStateAbortV2,
  freezeActivityReadStateConfigV2,
  freezeActivityReadStateRequestV2,
  prepareActivityReadStateInputV2,
  requireActivityReadStateResultV2,
  type ActivityReadStateInputV2,
  type ActivityReadStateMethodV2,
  type DesktopProjectActivityReadStateAuthorityV2,
} from './desktopProjectActivityReadStateOperationContractV2';
export function createDesktopProjectActivityReadStateHttpProjectionV2(
  config: DesktopRuntimeConfig,
  options: Readonly<{ retryStore?: ActivityReadRetryStore }> = {},
): DesktopProjectActivityReadStateAuthorityV2 {
  const runtime = freezeActivityReadStateConfigV2(config);
  return Object.freeze({
    async execute(method: ActivityReadStateMethodV2, input: ActivityReadStateInputV2) {
      if (
        Object.keys(runtime).some(
          (key) =>
            runtime[key as keyof DesktopRuntimeConfig] !==
            input.config[key as keyof DesktopRuntimeConfig],
        )
      )
        throw activityReadStateErrorV2(
          'project_activity_read_state_projection_config_mismatch',
          409,
        );
      const p = prepareActivityReadStateInputV2(method, { ...input, config: runtime });
      const projectPath = `/api/v1/projects/${encodeURIComponent(p.scope.projectId)}`;
      if (runtime.mode === 'cloud') {
        const project = await requestJson(
          p,
          projectPath + '?' + new URLSearchParams({ tenant_id: p.scope.tenantId }),
        );
        if (
          !activityReadStateRecordV2(project) ||
          project.id !== p.scope.projectId ||
          project.tenant_id !== p.scope.tenantId
        )
          throw activityReadStateErrorV2('project_activity_read_state_project_mismatch', 409);
      }
      const path = projectPath + '/activity/read-state';
      const read = async () =>
        parseActivityReadState(
          await requestJson(p, path),
          p.scope,
          'project_activity_read_state_response_invalid',
        );
      if (method === 'getActivityReadState')
        return requireActivityReadStateResultV2(method, await read(), p);
      checkActivityReadStateAbortV2(p.signal);
      // Storage access is deliberately lazy and belongs to the admitted operation.
      const store = options.retryStore ?? createLocalStorageActivityReadRetryStore();
      const put = async (
        request: UpdateActivityReadStateRequest,
      ): Promise<ActivityReadUpdateResult> => {
        let payload: unknown;
        try {
          payload = await requestJson(p, path, request);
        } catch (error) {
          checkActivityReadStateAbortV2(p.signal);
          if (
            !(error instanceof DesktopApiError) ||
            error.status !== 0 ||
            error.message !== 'project_activity_read_state_network_unavailable'
          )
            throw error;
          store.save(p.scope, request.entries);
          return {
            kind: 'queued_offline',
            availability: 'degraded',
            reasonCode:
              p.scope.authority === 'cloud'
                ? 'cloud_activity_read_state_offline_retry_pending'
                : 'local_activity_read_state_offline_retry_pending',
            expectedAuthorityRevision: request.expected_authority_revision,
            entries: store.load(p.scope),
          };
        }
        const state = parseActivityReadState(
          payload,
          p.scope,
          'project_activity_read_state_response_invalid',
        );
        checkActivityReadStateAbortV2(p.signal);
        store.acknowledge(p.scope, request.entries);
        return { kind: 'synced', state };
      };
      let result: ActivityReadUpdateResult;
      if (method === 'putActivityReadState') result = await put(p.request!);
      else {
        const pending = freezeActivityReadStateRequestV2({
          expected_authority_revision: 0,
          entries: store.load(p.scope),
        }).entries;
        const state = await read();
        checkActivityReadStateAbortV2(p.signal);
        result =
          pending.length === 0
            ? { kind: 'synced', state }
            : await put(
                freezeActivityReadStateRequestV2({
                  expected_authority_revision: state.authority_revision,
                  entries: pending,
                }),
              );
      }
      checkActivityReadStateAbortV2(p.signal);
      return requireActivityReadStateResultV2(method, result, p);
    },
  });
}
async function requestJson(
  input: ActivityReadStateInputV2,
  path: string,
  body?: UpdateActivityReadStateRequest,
): Promise<unknown> {
  const { config, signal } = input;
  checkActivityReadStateAbortV2(signal);
  if (!desktopApiAuthenticationAvailable(config))
    throw activityReadStateErrorV2('desktop_trusted_session_required', 401);
  const launch = desktopLaunchCapability(config);
  if (config.mode === 'local' && !launch)
    throw activityReadStateErrorV2('local_activity_authority_launch_capability_required', 401);
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  if (launch) headers.set('X-Agistack-Launch', launch);
  if (body !== undefined) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await desktopApiFetch(config, path, {
      method: body === undefined ? 'GET' : 'PUT',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    checkActivityReadStateAbortV2(signal);
    // Native policy/IPC/schema errors are not proof of a network outage.
    if (error instanceof TypeError && (config.mode === 'local' || config.apiKey.trim()))
      throw activityReadStateErrorV2('project_activity_read_state_network_unavailable', 0);
    throw error;
  }
  checkActivityReadStateAbortV2(signal);
  const isJson = response.headers.get('content-type')?.toLowerCase().includes('application/json');
  const raw: unknown = isJson ? await response.json().catch(() => null) : null;
  checkActivityReadStateAbortV2(signal);
  if (
    body !== undefined &&
    config.mode === 'cloud' &&
    !config.apiKey.trim() &&
    response.status === 503 &&
    activityReadStateRecordV2(raw) &&
    Object.keys(raw).length === 1 &&
    raw.reason_code === 'activity_read_state_transport_unavailable'
  ) {
    throw activityReadStateErrorV2('project_activity_read_state_network_unavailable', 0);
  }
  if (!response.ok) {
    const detail = activityReadStateRecordV2(raw) ? raw.detail : undefined;
    // Preserve structured CAS conflict information without propagating arbitrary error fields.
    const safeDetail = activityReadStateRecordV2(detail)
      ? Object.fromEntries(
          Object.entries(detail).filter(
            ([key, value]) =>
              [
                'code',
                'reason_code',
                'expected_authority_revision',
                'actual_authority_revision',
                'current_authority_revision',
              ].includes(key) &&
              (typeof value === 'string' || Number.isSafeInteger(value)),
          ),
        )
      : undefined;
    throw new DesktopApiError(`HTTP ${response.status}`, response.status, {
      reason_code: 'project_activity_read_state_http_error',
      ...(safeDetail ? { detail: safeDetail } : {}),
    });
  }
  if (!isJson || raw === null)
    throw activityReadStateErrorV2('project_activity_read_state_response_invalid', 502);
  return raw;
}
