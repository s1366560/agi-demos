import { DesktopApiError } from '../api/client';
import type { DesktopRuntimeConfig } from '../types';
import {
  parseActivityReadState,
  requireActivityReadUpdateRequest,
} from '../features/agent-authority/agentAuthorityContract';
import type {
  ActivityAuthorityScope,
  ActivityReadState,
  ActivityReadUpdateResult,
  UpdateActivityReadStateRequest,
} from '../features/agent-authority/agentAuthorityTypes';
export const ACTIVITY_READ_STATE_METHODS_V2 = [
  'getActivityReadState',
  'putActivityReadState',
  'flushPendingActivityReadState',
] as const;
export type ActivityReadStateMethodV2 = (typeof ACTIVITY_READ_STATE_METHODS_V2)[number];
export type ActivityReadStateResultsV2 = {
  getActivityReadState: ActivityReadState;
  putActivityReadState: ActivityReadUpdateResult;
  flushPendingActivityReadState: ActivityReadUpdateResult;
};
export type ActivityReadStateInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ActivityAuthorityScope;
  request?: UpdateActivityReadStateRequest;
  signal?: AbortSignal;
}>;
export interface DesktopProjectActivityReadStateAuthorityV2 {
  execute(method: ActivityReadStateMethodV2, input: ActivityReadStateInputV2): Promise<unknown>;
}
export function activityReadStateErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, Object.freeze({ code, reason_code: code }));
}
export function activityReadStateRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function freezeActivityReadStateConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  const keys = [
    'apiBaseUrl',
    'deviceAuthorizationBaseUrl',
    'apiKey',
    'localApiToken',
    'tenantId',
    'projectId',
    'workspaceId',
    'mode',
    'workspaceRoot',
  ];
  if (
    !activityReadStateRecordV2(config) ||
    Object.keys(config).length !== keys.length ||
    keys.some((key) => typeof config[key as keyof DesktopRuntimeConfig] !== 'string') ||
    !['cloud', 'local'].includes(config.mode)
  )
    throw activityReadStateErrorV2('project_activity_read_state_config_invalid');
  return Object.freeze({ ...config });
}
export function checkActivityReadStateAbortV2(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
}
export function prepareActivityReadStateInputV2(
  method: ActivityReadStateMethodV2,
  input: ActivityReadStateInputV2,
): ActivityReadStateInputV2 {
  if (
    !ACTIVITY_READ_STATE_METHODS_V2.includes(method) ||
    !activityReadStateRecordV2(input) ||
    !activityReadStateRecordV2(input.scope) ||
    Object.keys(input.scope).length !== 4
  )
    throw activityReadStateErrorV2('project_activity_read_state_input_invalid');
  const config = freezeActivityReadStateConfigV2(input.config);
  const { authority, principalId, tenantId, projectId } = input.scope;
  if (
    ![principalId, tenantId, projectId].every(
      (value) => typeof value === 'string' && value.length > 0 && value === value.trim(),
    )
  )
    throw activityReadStateErrorV2('project_activity_read_state_scope_invalid');
  if (
    authority !== config.mode ||
    tenantId !== config.tenantId ||
    projectId !== config.projectId ||
    (authority === 'local' && principalId !== 'local-user')
  )
    throw activityReadStateErrorV2('project_activity_read_state_scope_mismatch', 409);
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal))
    throw activityReadStateErrorV2('project_activity_read_state_signal_invalid');
  checkActivityReadStateAbortV2(input.signal);
  const request =
    method === 'putActivityReadState'
      ? freezeActivityReadStateRequestV2(input.request as UpdateActivityReadStateRequest)
      : undefined;
  if (method !== 'putActivityReadState' && input.request !== undefined)
    throw activityReadStateErrorV2('project_activity_read_state_request_invalid');
  return Object.freeze({
    config,
    scope: Object.freeze({ authority, principalId, tenantId, projectId }),
    ...(request === undefined ? {} : { request }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
export function freezeActivityReadStateRequestV2(
  request: UpdateActivityReadStateRequest,
): UpdateActivityReadStateRequest {
  const parsed = requireActivityReadUpdateRequest(
    request,
    'project_activity_read_state_request_invalid',
  );
  return Object.freeze({
    ...parsed,
    entries: Object.freeze(parsed.entries.map((entry) => Object.freeze({ ...entry }))),
  });
}
export function requireActivityReadStateResultV2<K extends ActivityReadStateMethodV2>(
  method: K,
  raw: unknown,
  input: ActivityReadStateInputV2,
): ActivityReadStateResultsV2[K] {
  const state = (value: unknown) => {
    const parsed = parseActivityReadState(
      value,
      input.scope,
      'project_activity_read_state_response_invalid',
    );
    return Object.freeze({
      ...parsed,
      entries: Object.freeze(parsed.entries.map((entry) => Object.freeze({ ...entry }))),
    });
  };
  let result: ActivityReadState | ActivityReadUpdateResult;
  if (method === 'getActivityReadState') result = state(raw);
  else if (activityReadStateRecordV2(raw) && raw.kind === 'synced')
    result = Object.freeze({ kind: 'synced', state: state(raw.state) });
  else if (
    activityReadStateRecordV2(raw) &&
    raw.kind === 'queued_offline' &&
    raw.availability === 'degraded' &&
    raw.reasonCode === `${input.scope.authority}_activity_read_state_offline_retry_pending`
  ) {
    const request = freezeActivityReadStateRequestV2({
      expected_authority_revision: raw.expectedAuthorityRevision,
      entries: raw.entries,
    } as UpdateActivityReadStateRequest);
    if (
      method === 'putActivityReadState' &&
      request.expected_authority_revision !== input.request?.expected_authority_revision
    )
      throw activityReadStateErrorV2('project_activity_read_state_response_invalid', 502);
    result = Object.freeze({
      kind: 'queued_offline',
      availability: 'degraded',
      reasonCode:
        input.scope.authority === 'cloud'
          ? 'cloud_activity_read_state_offline_retry_pending'
          : 'local_activity_read_state_offline_retry_pending',
      expectedAuthorityRevision: request.expected_authority_revision,
      entries: request.entries,
    });
  } else throw activityReadStateErrorV2('project_activity_read_state_response_invalid', 502);
  return result as ActivityReadStateResultsV2[K];
}
