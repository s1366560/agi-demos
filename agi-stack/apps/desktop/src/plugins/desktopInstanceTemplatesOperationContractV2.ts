import { RuntimeV2Error } from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type {
  InstanceTemplateCreateInput,
  InstanceTemplatesQuery,
  InstanceTemplatesScope,
} from '../features/instance-templates/instanceTemplatesTypes';
export type DesktopInstanceTemplatesBaseInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: InstanceTemplatesScope;
  signal?: AbortSignal;
}>;
export type PreparedDesktopInstanceTemplatesBaseV2 =
  DesktopInstanceTemplatesBaseInputV2;
const KEYS = new Set([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'workspaceRoot',
  'mode',
]);
export function prepareDesktopInstanceTemplatesBaseV2(
  i: DesktopInstanceTemplatesBaseInputV2,
): PreparedDesktopInstanceTemplatesBaseV2 {
  if (!record(i)) throw invalid();
  const config = cloneDesktopInstanceTemplatesConfigV2(i.config);
  if (
    !record(i.scope) ||
    Object.keys(i.scope).length !== 2 ||
    i.scope.authority !== config.mode ||
    id(i.scope.tenantId) !== config.tenantId
  )
    throw invalid();
  if (i.signal !== undefined && !signal(i.signal)) throw invalid();
  return Object.freeze({
    config,
    scope: Object.freeze({ ...i.scope }),
    ...(i.signal === undefined ? {} : { signal: i.signal }),
  });
}
export function cloneDesktopInstanceTemplatesConfigV2(
  c: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !record(c) ||
    Object.keys(c).length !== KEYS.size ||
    Object.keys(c).some((k) => !KEYS.has(k)) ||
    Object.values(c).some((v) => typeof v !== 'string') ||
    (c.mode !== 'cloud' && c.mode !== 'local')
  )
    throw invalid();
  id(c.tenantId);
  return Object.freeze({ ...c });
}
export function prepareDesktopInstanceTemplatesIdV2(v: string): string {
  return id(v);
}
export function prepareDesktopInstanceTemplatesNameV2(v: string): string {
  return id(v);
}
export function prepareDesktopInstanceTemplatesQueryV2(
  v: InstanceTemplatesQuery | undefined,
): InstanceTemplatesQuery {
  const q = v ?? {};
  if (
    !record(q) ||
    Object.keys(q).some(
      (k) =>
        !['page', 'pageSize', 'search', 'status', 'isPublished'].includes(k),
    ) ||
    (q.page !== undefined && (!Number.isSafeInteger(q.page) || q.page < 1)) ||
    (q.pageSize !== undefined &&
      (!Number.isSafeInteger(q.pageSize) ||
        q.pageSize < 1 ||
        q.pageSize > 100)) ||
    (q.search !== undefined &&
      (typeof q.search !== 'string' || q.search.length > 200)) ||
    (q.status !== undefined &&
      !['all', 'published', 'draft'].includes(q.status)) ||
    (q.isPublished !== undefined && typeof q.isPublished !== 'boolean')
  )
    throw invalid();
  return Object.freeze({ ...q });
}
export function prepareDesktopInstanceTemplateCreateV2(
  v: InstanceTemplateCreateInput,
): InstanceTemplateCreateInput {
  if (
    !record(v) ||
    Object.keys(v).length !== 4 ||
    !record(v.defaultConfig) ||
    (typeof v.description !== 'string' && v.description !== null)
  )
    throw invalid();
  return Object.freeze({
    name: id(v.name),
    slug: id(v.slug),
    description: v.description,
    defaultConfig: Object.freeze({ ...v.defaultConfig }),
  });
}
function id(v: unknown): string {
  if (typeof v !== 'string' || !v || v !== v.trim() || v.length > 256)
    throw invalid();
  return v;
}
function signal(v: unknown): v is AbortSignal {
  return (
    record(v) &&
    typeof v.aborted === 'boolean' &&
    typeof v.addEventListener === 'function'
  );
}
function record(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}
function invalid() {
  return new RuntimeV2Error(
    'desktop_instance_templates_operation_input_invalid',
    'desktop instance templates operation input invalid',
  );
}
