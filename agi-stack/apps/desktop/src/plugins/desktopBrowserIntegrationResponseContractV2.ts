import type {
  BrowserOriginGrant,
  BrowserCapabilityGrant,
  BrowserSiteCredentialMeta,
  BrowserAuditEntry,
} from '../types';
import {
  browserIntegrationRecordV2,
  browserIntegrationErrorV2,
  freezeBrowserIntegrationJsonV2,
  type BrowserIntegrationMethodV2,
  type BrowserIntegrationInputV2,
  type BrowserIntegrationResultsV2,
} from './desktopBrowserIntegrationOperationContractV2';
function invalid(): never {
  throw browserIntegrationErrorV2('browser_integration_response_invalid', 502);
}
function record(raw: unknown): Record<string, unknown> {
  if (!browserIntegrationRecordV2(raw)) invalid();
  return raw;
}
function string(raw: Record<string, unknown>, snake: string, camel?: string): string {
  const value = raw[snake] ?? (camel ? raw[camel] : undefined);
  return typeof value === 'string' ? value.trim() : '';
}
function originGrant(value: unknown): BrowserOriginGrant {
  const raw = record(value);
  const id = string(raw, 'id');
  const host = string(raw, 'host');
  const decision = string(raw, 'decision');
  const createdAt = string(raw, 'created_at', 'createdAt');
  if (
    !id ||
    !host ||
    !createdAt ||
    (decision !== 'site' && decision !== 'all' && decision !== 'decline')
  )
    invalid();
  return {
    id,
    host,
    decision,
    source_hitl_request_id: string(raw, 'source_hitl_request_id', 'sourceHitlRequestId'),
    created_at: createdAt,
  };
}
function capabilityGrant(value: unknown): BrowserCapabilityGrant {
  const raw = record(value);
  const id = string(raw, 'id');
  const host = string(raw, 'host');
  const capability = string(raw, 'capability');
  const decision = string(raw, 'decision');
  const createdAt = string(raw, 'created_at', 'createdAt');
  if (
    !id ||
    !host ||
    !createdAt ||
    capability !== 'full_cdp' ||
    (decision !== 'site' && decision !== 'decline')
  )
    invalid();
  return {
    id,
    host,
    capability,
    decision,
    source_hitl_request_id: string(raw, 'source_hitl_request_id', 'sourceHitlRequestId'),
    created_at: createdAt,
  };
}
function credential(value: unknown): BrowserSiteCredentialMeta {
  const raw = record(value);
  const id = string(raw, 'id');
  const origin = string(raw, 'origin');
  const username = string(raw, 'username');
  const createdAt = string(raw, 'created_at', 'createdAt');
  if (!id || !origin || !username || !createdAt) invalid();
  // The authority returns metadata only, even if an adapter mistakenly adds vault data.
  return { id, origin, username, created_at: createdAt };
}
function audit(value: unknown): BrowserAuditEntry {
  const raw = record(value);
  const id =
    Number.isSafeInteger(raw.id) && Number(raw.id) >= 0 ? String(raw.id) : string(raw, 'id');
  const rawTime = raw.created_at ?? raw.createdAt;
  let createdAt = string(raw, 'created_at', 'createdAt');
  if (typeof rawTime === 'number') {
    if (
      !Number.isSafeInteger(rawTime) ||
      rawTime < 0 ||
      !Number.isFinite(new Date(rawTime).getTime())
    )
      invalid();
    createdAt = new Date(rawTime).toISOString();
  }
  const tool = string(raw, 'tool_name', 'toolName');
  const outcome = string(raw, 'outcome');
  const latency = raw.latency_ms ?? raw.latencyMs;
  if (
    !id ||
    !createdAt ||
    !tool ||
    !['ok', 'consent', 'error', 'denied', 'consent_required', 'declined'].includes(outcome) ||
    !Number.isSafeInteger(latency) ||
    Number(latency) < 0
  )
    invalid();
  return {
    id,
    run_id: string(raw, 'run_id', 'runId'),
    tool_name: tool,
    origin: string(raw, 'origin'),
    target_summary: string(raw, 'target_summary', 'targetSummary'),
    outcome: outcome as BrowserAuditEntry['outcome'],
    latency_ms: latency as number,
    created_at: createdAt,
  };
}
function list(raw: unknown, key: string): unknown[] {
  const value = Array.isArray(raw) ? raw : record(raw)[key];
  if (!Array.isArray(value)) invalid();
  return value;
}
function item(raw: unknown, key: string): unknown {
  const value = record(raw);
  if (value.success !== undefined && value.success !== true) invalid();
  return Object.hasOwn(value, key) ? value[key] : value;
}
export function requireBrowserIntegrationResultV2<K extends BrowserIntegrationMethodV2>(
  method: K,
  raw: unknown,
  input: BrowserIntegrationInputV2<K>,
): BrowserIntegrationResultsV2[K] {
  let result: unknown;
  switch (method) {
    case 'listBrowserOriginGrants':
      result = list(raw, 'grants').map(originGrant);
      break;
    case 'listBrowserCapabilityGrants':
      result = list(raw, 'grants').map(capabilityGrant);
      break;
    case 'listBrowserSiteCredentials':
      result = list(raw, 'credentials').map(credential);
      break;
    case 'listBrowserAuditEntries':
      result = list(raw, 'entries').map(audit);
      break;
    case 'revokeBrowserOriginGrant':
      result = originGrant(item(raw, 'grant'));
      break;
    case 'revokeBrowserCapabilityGrant':
      result = capabilityGrant(item(raw, 'grant'));
      break;
    case 'upsertBrowserSiteCredential':
      result = credential(item(raw, 'credential'));
      break;
    case 'deleteBrowserSiteCredential':
      result = credential(item(raw, 'credential'));
      break;
  }
  if (
    [
      'revokeBrowserOriginGrant',
      'revokeBrowserCapabilityGrant',
      'deleteBrowserSiteCredential',
    ].includes(method) &&
    record(result).id !== input.args[0]
  )
    invalid();
  return freezeBrowserIntegrationJsonV2(result) as BrowserIntegrationResultsV2[K];
}
