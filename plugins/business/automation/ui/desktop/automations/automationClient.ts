import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '@desktop/api/client';
import type { DesktopApiClient } from '@desktop/api/client';
import { desktopApiFetch } from '@desktop/api/cloudRequestBroker';
import type {
  AutomationCapabilities,
  AutomationCreateInput,
  AutomationDeleteInput,
  AutomationJob,
  AutomationToggleInput,
  AutomationUpdateInput,
  DesktopRuntimeConfig,
} from '@desktop/types';
import { normalizeAutomationCapabilityEnvelope } from './automationModel';

import { AutomationRunOutcomeUnknownError, type AutomationRunInput, type AutomationRunReceipt } from './automationRunAttempt';
export { AutomationRunOutcomeUnknownError, automationRunAttemptKey, settleAutomationRunAttempt, type AutomationRunInput, type AutomationRunReceipt } from './automationRunAttempt';

const DEFINITE_CLIENT_ERROR_STATUSES = new Set([
  400, 401, 403, 404, 405, 409, 410, 412, 413, 415, 422,
]);

const AUTOMATION_RUN_RECEIPT_STATUSES = new Set([
  'queued',
  'running',
  'waiting_human',
  'success',
  'failed',
  'timeout',
  'cancelled',
]);

type DesktopAutomationMutationApi = Pick<
  DesktopApiClient,
  | 'createAutomation'
  | 'deleteAutomation'
  | 'listAutomations'
  | 'listAutomationRuns'
  | 'toggleAutomation'
  | 'updateAutomation'
>;

export type DesktopAutomationApi = DesktopAutomationMutationApi & {
  getAutomationCapabilities(
    projectId?: string,
    signal?: AbortSignal,
  ): Promise<AutomationCapabilities>;
  runAutomation(
    automationId: string,
    input: AutomationRunInput,
    projectId?: string,
  ): Promise<AutomationRunReceipt>;
};

type BaseAutomationApi = Pick<
  DesktopApiClient,
  | 'createAutomation'
  | 'deleteAutomation'
  | 'getAutomationCapabilities'
  | 'listAutomations'
  | 'listAutomationRuns'
  | 'toggleAutomation'
  | 'updateAutomation'
>;

export function createDesktopAutomationApi(
  baseApi: BaseAutomationApi,
  config: DesktopRuntimeConfig,
): DesktopAutomationApi {
  return {
    createAutomation: (input, projectId) =>
      baseApi.createAutomation(
        config.mode === 'local' && config.workspaceId.trim()
          ? { ...input, workspace_id: input.workspace_id ?? config.workspaceId.trim() }
          : input,
        projectId,
      ),
    deleteAutomation: (...args: Parameters<BaseAutomationApi['deleteAutomation']>) =>
      baseApi.deleteAutomation(...args),
    getAutomationCapabilities: async (
      ...args: Parameters<BaseAutomationApi['getAutomationCapabilities']>
    ) => {
      const capabilities = normalizeAutomationCapabilityEnvelope(
        await baseApi.getAutomationCapabilities(...args),
      );
      if (!capabilities) throw new Error('automation capability contract is invalid');
      return capabilities;
    },
    listAutomations: (...args: Parameters<BaseAutomationApi['listAutomations']>) =>
      baseApi.listAutomations(...args),
    listAutomationRuns: (...args: Parameters<BaseAutomationApi['listAutomationRuns']>) =>
      baseApi.listAutomationRuns(...args),
    toggleAutomation: (...args: Parameters<BaseAutomationApi['toggleAutomation']>) =>
      baseApi.toggleAutomation(...args),
    updateAutomation: (...args: Parameters<BaseAutomationApi['updateAutomation']>) =>
      baseApi.updateAutomation(...args),
    runAutomation: (automationId, input, projectId = config.projectId) =>
      runAutomation(config, projectId, automationId, input),
  };
}

async function runAutomation(
  config: DesktopRuntimeConfig,
  projectId: string,
  automationId: string,
  input: AutomationRunInput,
): Promise<AutomationRunReceipt> {
  const resolvedProjectId = requireValue(projectId, 'project id');
  const resolvedAutomationId = requireValue(automationId, 'automation id');
  requirePositiveInteger(input.expected_revision, 'expected revision');
  requireIdempotencyKey(input.idempotency_key);
  if (input.conversation_id != null) {
    requireValue(input.conversation_id, 'conversation id');
  }

  const headers = new Headers({
    Accept: 'application/json',
    'Content-Type': 'application/json',
  });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);

  let response: Response;
  try {
    response = await desktopApiFetch(
      config,
      `/api/v1/projects/${encodeURIComponent(
        resolvedProjectId,
      )}/cron-jobs/${encodeURIComponent(resolvedAutomationId)}/run`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({ ...input, contract_version: 2 }),
      },
    );
  } catch {
    throw new AutomationRunOutcomeUnknownError();
  }
  const definiteClientError = DEFINITE_CLIENT_ERROR_STATUSES.has(response.status);
  const contentType = response.headers.get('content-type') ?? '';
  let payload: unknown;
  try {
    payload = contentType.includes('application/json')
      ? await response.json()
      : await response.text();
  } catch {
    if (!definiteClientError) throw new AutomationRunOutcomeUnknownError();
    payload = null;
  }
  if (!response.ok) {
    if (!definiteClientError) throw new AutomationRunOutcomeUnknownError();
    const message =
      isRecord(payload) && 'detail' in payload ? String(payload.detail) : `HTTP ${response.status}`;
    throw new DesktopApiError(message, response.status, payload);
  }
  try {
    return requireAutomationRunReceipt(payload, resolvedAutomationId);
  } catch {
    throw new AutomationRunOutcomeUnknownError();
  }
}

function requireAutomationRunReceipt(
  payload: unknown,
  expectedAutomationId: string,
): AutomationRunReceipt {
  if (
    !isRecord(payload) ||
    typeof payload.receipt_id !== 'string' ||
    typeof payload.run_id !== 'string' ||
    typeof payload.job_id !== 'string' ||
    typeof payload.status !== 'string' ||
    typeof payload.duplicate !== 'boolean'
  ) {
    throw new Error('automation run receipt is invalid');
  }
  const jobId = requireValue(payload.job_id, 'job id');
  const status = requireValue(payload.status, 'run status');
  if (jobId !== expectedAutomationId || !AUTOMATION_RUN_RECEIPT_STATUSES.has(status)) {
    throw new Error('automation run receipt does not match the requested job or status contract');
  }
  return {
    receipt_id: requireValue(payload.receipt_id, 'receipt id'),
    run_id: requireValue(payload.run_id, 'run id'),
    job_id: jobId,
    status,
    duplicate: payload.duplicate,
  };
}

function requireValue(value: string, label: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${label} is required`);
  return normalized;
}

function requirePositiveInteger(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error(`${label} must be a positive integer`);
  }
}

function requireIdempotencyKey(value: string): void {
  if (
    !value ||
    value.length > 255 ||
    [...value].some((character) => {
      const code = character.charCodeAt(0);
      return code < 33 || code > 126;
    })
  ) {
    throw new Error('idempotency key must contain 1 to 255 visible ASCII characters');
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
