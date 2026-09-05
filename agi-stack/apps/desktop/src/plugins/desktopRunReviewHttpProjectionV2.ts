import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import {
  checkRunReviewAbortV2,
  prepareRunReviewRequestV2,
  prepareRunChangesScopeV2,
  requireRunReviewSummaryV2,
  requireRunReviewChangesV2,
  runReviewErrorV2,
  type DesktopRunReviewIdentityV2,
  type DesktopRunChangesScopeV2,
} from './desktopRunReviewContractV2';
export function createDesktopRunReviewHttpProjectionV2(config: DesktopRuntimeConfig) {
  const runtime = Object.freeze({ ...config });
  const summary = async (
    identity: DesktopRunReviewIdentityV2,
    runId: string,
    signal: AbortSignal,
  ) => {
    prepareRunReviewRequestV2(runtime, identity, runId, signal);
    if (runtime.mode !== 'cloud') throw runReviewErrorV2('local_run_summary_unavailable', 501);
    const raw = await requestJson(
      runtime,
      `/api/v1/agent/runs/${encodeURIComponent(runId)}/summary`,
      signal,
    );
    return requireRunReviewSummaryV2(raw, identity, runId);
  };
  return Object.freeze({
    getRunSummary: summary,
    async getRunChanges(
      identity: DesktopRunReviewIdentityV2,
      runId: string,
      expectedRevision: number,
      signal: AbortSignal,
      options: DesktopRunChangesScopeV2 = {},
    ) {
      prepareRunReviewRequestV2(runtime, identity, runId, signal);
      const request = prepareRunChangesScopeV2(runtime, expectedRevision, options);
      if (runtime.mode === 'local' && request.scope !== 'run')
        throw runReviewErrorV2('local_run_changes_scope_unavailable', 501);
      if (runtime.mode === 'cloud') await summary(identity, runId, signal);
      checkRunReviewAbortV2(signal);
      const params = new URLSearchParams(
        runtime.mode === 'cloud'
          ? { scope: request.scope, expected_revision: String(expectedRevision) }
          : { expected_revision: String(expectedRevision) },
      );
      if (runtime.mode === 'cloud' && request.turnId) params.set('turn_id', request.turnId);
      const raw = await requestJson(
        runtime,
        `/api/v1/agent/runs/${encodeURIComponent(runId)}/changes?${params}`,
        signal,
      );
      return requireRunReviewChangesV2(raw, runtime, identity, runId, expectedRevision, request);
    },
  });
}
async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  signal: AbortSignal,
): Promise<unknown> {
  checkRunReviewAbortV2(signal);
  if (!desktopApiAuthenticationAvailable(config))
    throw runReviewErrorV2('desktop_trusted_session_required', 401);
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launch = desktopLaunchCapability(config);
  if (config.mode === 'local' && !launch)
    throw runReviewErrorV2('desktop_local_launch_required', 401);
  if (launch) headers.set('X-Agistack-Launch', launch);
  const response = await desktopApiFetch(config, path, { method: 'GET', headers, signal });
  checkRunReviewAbortV2(signal);
  const raw: unknown = response.headers
    .get('content-type')
    ?.toLowerCase()
    .includes('application/json')
    ? await response.json().catch(() => null)
    : null;
  checkRunReviewAbortV2(signal);
  if (!response.ok) {
    const record =
      raw !== null && typeof raw === 'object' && !Array.isArray(raw)
        ? (raw as Record<string, unknown>)
        : {};
    const detail = typeof record.detail === 'string' ? record.detail : undefined;
    throw new DesktopApiError(detail ?? `HTTP ${response.status}`, response.status, raw);
  }
  if (raw === null) throw runReviewErrorV2('desktop_run_review_response_invalid', 502);
  return raw;
}
