import { RuntimeV2Error, type ScopeV2 } from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import { resolveMarkdownArtifactImage } from '../features/chat/markdownArtifactImageModel';
import { isSafeArtifactUrl } from '../features/chat/assistantArtifactReferenceModel';

export const STRUCTURED_IMAGE_PREVIEW_MAX_BYTES_V2 = 25 * 1024 * 1024;
export type ImagePreviewOwnerV2 = Readonly<
  | { kind: 'conversation'; tenantId: string; projectId: string; id: string }
  | { kind: 'workspace'; tenantId: string; projectId: string; id: string }
>;
export type StructuredImagePreviewInputV2 = Readonly<{
  source: string;
  carriers: readonly unknown[];
  signal: AbortSignal;
}>;
export type PreparedStructuredImagePreviewV2 = StructuredImagePreviewInputV2 &
  Readonly<{
    config: DesktopRuntimeConfig;
    owner: ImagePreviewOwnerV2;
    scope: ScopeV2;
  }>;

export function freezeImagePreviewConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  return Object.freeze({
    apiBaseUrl: config.apiBaseUrl,
    apiKey: config.apiKey,
    mode: config.mode,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    workspaceRoot: config.workspaceRoot,
  });
}
export function freezeImagePreviewOwnerV2(owner: ImagePreviewOwnerV2): ImagePreviewOwnerV2 {
  return Object.freeze({
    kind: owner.kind,
    tenantId: owner.tenantId,
    projectId: owner.projectId,
    id: owner.id,
  });
}
export function prepareStructuredImagePreviewV2(
  config: DesktopRuntimeConfig,
  owner: ImagePreviewOwnerV2,
  input: StructuredImagePreviewInputV2,
): PreparedStructuredImagePreviewV2 {
  if (
    Object.values(config).some((value) => typeof value !== 'string') ||
    !['cloud', 'local'].includes(config.mode) ||
    !canonical(owner.tenantId) ||
    !canonical(owner.projectId) ||
    !canonical(owner.id) ||
    !['workspace', 'conversation'].includes(owner.kind) ||
    owner.tenantId !== config.tenantId ||
    owner.projectId !== config.projectId ||
    (owner.kind === 'workspace' && owner.id !== config.workspaceId)
  )
    throw imagePreviewErrorV2('scope_mismatch');
  if (
    !input ||
    typeof input.source !== 'string' ||
    !input.source.trim() ||
    !Array.isArray(input.carriers) ||
    !(input.signal instanceof AbortSignal)
  )
    throw imagePreviewErrorV2('input_invalid');
  input.signal.throwIfAborted();
  const carriers = freezeImagePreviewCarriersV2(input.carriers, owner);
  const scope: ScopeV2 =
    owner.kind === 'conversation'
      ? {
          kind: 'session',
          tenant_id: owner.tenantId,
          project_id: owner.projectId,
          session_id: owner.id,
        }
      : { kind: 'project', tenant_id: owner.tenantId, project_id: owner.projectId };
  return Object.freeze({
    config,
    owner,
    source: input.source,
    carriers,
    signal: input.signal,
    scope: Object.freeze(scope),
  });
}
export function freezeImagePreviewCarriersV2(
  carriers: readonly unknown[],
  owner: ImagePreviewOwnerV2,
): readonly unknown[] {
  if (!Array.isArray(carriers)) throw imagePreviewErrorV2('input_invalid');
  const frozen = cloneJson(carriers, new Set()) as readonly unknown[];
  for (const carrier of frozen) validateCarrierOwner(carrier, owner);
  return frozen;
}
export function resolveStructuredImagePreviewUrlV2(
  input: PreparedStructuredImagePreviewV2,
): string {
  const resolution = resolveMarkdownArtifactImage(input.source, input.carriers);
  if (!resolution) throw imagePreviewErrorV2('reference_unavailable');
  validateImagePreviewUrlV2(resolution.url);
  return resolution.url;
}
export function validateImagePreviewUrlV2(url: string): void {
  if (!isSafeArtifactUrl(url)) throw imagePreviewErrorV2('url_invalid');
  const parsed = new URL(url);
  if (parsed.username || parsed.password) throw imagePreviewErrorV2('url_invalid');
}
export function requireStructuredImagePreviewBlobV2(value: unknown): Blob {
  if (
    !(value instanceof Blob) ||
    value.size === 0 ||
    value.size > STRUCTURED_IMAGE_PREVIEW_MAX_BYTES_V2 ||
    !isImageMimeV2(value.type)
  )
    throw imagePreviewErrorV2('content_invalid');
  return value;
}
export function isImageMimeV2(value: string): boolean {
  return /^image\/[a-z0-9!#$&^_.+-]+$/iu.test(value.split(';', 1)[0].trim());
}
export function imagePreviewErrorV2(reason: string): RuntimeV2Error {
  return new RuntimeV2Error(
    `desktop_structured_image_preview_${reason}`,
    `structured image preview: ${reason}`,
  );
}
function canonical(value: unknown): value is string {
  return typeof value === 'string' && value.trim() === value && value.length > 0;
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function validateCarrierOwner(value: unknown, owner: ImagePreviewOwnerV2): void {
  if (!record(value)) return;
  for (const [keys, expected] of [
    [['tenant_id', 'tenantId'], owner.tenantId],
    [['project_id', 'projectId'], owner.projectId],
    [
      owner.kind === 'conversation'
        ? ['conversation_id', 'conversationId']
        : ['workspace_id', 'workspaceId'],
      owner.id,
    ],
  ] as const) {
    for (const key of keys) {
      if (value[key] !== undefined && value[key] !== null && value[key] !== expected)
        throw imagePreviewErrorV2('carrier_scope_mismatch');
    }
  }
  // Only protocol carrier containers are inspected, not arbitrary tool-output data.
  for (const key of ['payload', 'metadata']) validateCarrierOwner(value[key], owner);
  if (Array.isArray(value.artifacts))
    for (const item of value.artifacts) validateCarrierOwner(item, owner);
}
function cloneJson(value: unknown, ancestors: Set<object>): unknown {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (!record(value) && !Array.isArray(value)) throw imagePreviewErrorV2('input_invalid');
  if (ancestors.has(value)) throw imagePreviewErrorV2('input_invalid');
  ancestors.add(value);
  try {
    if (Array.isArray(value)) return Object.freeze(value.map((item) => cloneJson(item, ancestors)));
    const result: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value))
      if (item !== undefined)
        Object.defineProperty(result, key, { value: cloneJson(item, ancestors), enumerable: true });
    return Object.freeze(result);
  } finally {
    ancestors.delete(value);
  }
}
