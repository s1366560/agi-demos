import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { WorkspaceCreateInput, WorkspaceUpdateInput } from '../api/client';
import type { DesktopRuntimeConfig, WorkspaceSummary } from '../types';

const CREATE_INPUT_KEYS_V2 = new Set([
  'collaborationMode',
  'description',
  'metadata',
  'name',
  'sandboxCodeRoot',
  'useCase',
]);
const UPDATE_INPUT_KEYS_V2 = new Set([
  'description',
  'isArchived',
  'metadata',
  'name',
]);
const WORKSPACE_REQUIRED_KEYS_V2 = new Set(['id', 'name', 'project_id', 'tenant_id']);
const WORKSPACE_OPTIONAL_KEYS_V2 = new Set([
  'created_at',
  'created_by',
  'description',
  'hex_layout_config',
  'is_archived',
  'metadata',
  'office_status',
  'status',
  'title',
  'updated_at',
]);
const WORKSPACE_USE_CASES_V2 = new Set<WorkspaceCreateInput['useCase']>([
  'conversation',
  'general',
  'operations',
  'programming',
  'research',
]);
const WORKSPACE_COLLABORATION_MODES_V2 = new Set<
  WorkspaceCreateInput['collaborationMode']
>(['autonomous', 'multi_agent_isolated', 'multi_agent_shared', 'single_agent']);

export function cloneWorkspaceLifecycleRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw workspaceLifecycleInputInvalidV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalIdentifierV2(copy.apiBaseUrl) ||
    !isCanonicalIdentifierV2(copy.tenantId) ||
    !isCanonicalIdentifierV2(copy.projectId) ||
    (copy.workspaceId !== '' && !isCanonicalIdentifierV2(copy.workspaceId))
  ) {
    throw workspaceLifecycleInputInvalidV2();
  }
  return Object.freeze(copy);
}

export function cloneWorkspaceLifecycleCreateInputV2(
  value: unknown,
): WorkspaceCreateInput {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(
      value,
      new Set(['collaborationMode', 'description', 'metadata', 'name', 'useCase']),
      CREATE_INPUT_KEYS_V2,
    ) ||
    !isCanonicalIdentifierV2(value.name) ||
    !isTrimmedStringV2(value.description) ||
    typeof value.useCase !== 'string' ||
    !WORKSPACE_USE_CASES_V2.has(value.useCase as WorkspaceCreateInput['useCase']) ||
    typeof value.collaborationMode !== 'string' ||
    !WORKSPACE_COLLABORATION_MODES_V2.has(
      value.collaborationMode as WorkspaceCreateInput['collaborationMode'],
    ) ||
    (value.sandboxCodeRoot !== undefined &&
      !isCanonicalIdentifierV2(value.sandboxCodeRoot))
  ) {
    throw workspaceLifecycleInputInvalidV2();
  }
  return Object.freeze({
    name: value.name,
    description: value.description,
    useCase: value.useCase as WorkspaceCreateInput['useCase'],
    collaborationMode:
      value.collaborationMode as WorkspaceCreateInput['collaborationMode'],
    ...(value.sandboxCodeRoot === undefined
      ? {}
      : { sandboxCodeRoot: value.sandboxCodeRoot as string }),
    metadata: cloneJsonRecordV2(value.metadata),
  });
}

export function cloneWorkspaceLifecycleUpdateInputV2(
  value: unknown,
): WorkspaceUpdateInput {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, UPDATE_INPUT_KEYS_V2) ||
    !isCanonicalIdentifierV2(value.name) ||
    !isTrimmedStringV2(value.description) ||
    typeof value.isArchived !== 'boolean'
  ) {
    throw workspaceLifecycleInputInvalidV2();
  }
  return Object.freeze({
    name: value.name,
    description: value.description,
    isArchived: value.isArchived,
    metadata: cloneJsonRecordV2(value.metadata),
  });
}

export function cloneWorkspaceLifecycleWorkspaceIdV2(value: unknown): string {
  if (!isCanonicalIdentifierV2(value)) throw workspaceLifecycleInputInvalidV2();
  return value;
}

export function cloneWorkspaceLifecycleSignalV2(
  value: unknown,
): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw workspaceLifecycleInputInvalidV2();
  }
  return value;
}

export function assertWorkspaceLifecycleSignalV2(
  expected: AbortSignal | undefined,
  actual: AbortSignal | undefined,
): void {
  if (actual !== expected) throw workspaceLifecycleInputInvalidV2();
}

export function cloneWorkspaceLifecycleResponseV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  expectedWorkspaceId: string | null,
  expectedName: string,
): WorkspaceSummary {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(
      value,
      WORKSPACE_REQUIRED_KEYS_V2,
      new Set([...WORKSPACE_REQUIRED_KEYS_V2, ...WORKSPACE_OPTIONAL_KEYS_V2]),
    ) ||
    !isCanonicalIdentifierV2(value.id) ||
    (expectedWorkspaceId !== null && value.id !== expectedWorkspaceId) ||
    value.tenant_id !== config.tenantId ||
    value.project_id !== config.projectId ||
    value.name !== expectedName ||
    !isOptionalStringV2(value.title) ||
    !isOptionalCanonicalIdentifierV2(value.created_by) ||
    !isOptionalNullableStringV2(value.description) ||
    !isOptionalCanonicalIdentifierV2(value.status) ||
    !isOptionalBooleanV2(value.is_archived) ||
    !isOptionalCanonicalIdentifierV2(value.office_status) ||
    !isOptionalNullableJsonRecordV2(value.hex_layout_config) ||
    !isOptionalCanonicalIdentifierV2(value.created_at) ||
    !isOptionalNullableStringV2(value.updated_at) ||
    !isOptionalNullableJsonRecordV2(value.metadata)
  ) {
    throw workspaceLifecycleResponseInvalidV2();
  }
  return Object.freeze({
    id: value.id,
    tenant_id: config.tenantId,
    project_id: config.projectId,
    name: expectedName,
    ...(value.title === undefined ? {} : { title: value.title }),
    ...(value.created_by === undefined ? {} : { created_by: value.created_by }),
    ...(value.description === undefined ? {} : { description: value.description }),
    ...(value.status === undefined ? {} : { status: value.status }),
    ...(value.is_archived === undefined ? {} : { is_archived: value.is_archived }),
    ...(value.office_status === undefined ? {} : { office_status: value.office_status }),
    ...(value.hex_layout_config === undefined
      ? {}
      : {
          hex_layout_config:
            value.hex_layout_config === null
              ? null
              : cloneJsonRecordV2(value.hex_layout_config),
        }),
    ...(value.created_at === undefined ? {} : { created_at: value.created_at }),
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
    ...(value.metadata === undefined
      ? {}
      : {
          metadata: value.metadata === null ? null : cloneJsonRecordV2(value.metadata),
        }),
  });
}

export function workspaceLifecycleInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_lifecycle_input_invalid',
    'desktop workspace lifecycle operation input is invalid',
  );
}

export function workspaceLifecycleResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_lifecycle_response_invalid',
    'desktop workspace lifecycle response is invalid',
  );
}

export function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function cloneJsonRecordV2(value: unknown): Readonly<Record<string, unknown>> {
  if (!isPlainRecordV2(value)) throw workspaceLifecycleInputInvalidV2();
  return cloneJsonValueV2(value, new Set(), 0) as Readonly<Record<string, unknown>>;
}

function cloneJsonValueV2(value: unknown, ancestors: Set<object>, depth: number): unknown {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw workspaceLifecycleInputInvalidV2();
    return value;
  }
  if (depth >= 32 || (typeof value !== 'object' && !Array.isArray(value))) {
    throw workspaceLifecycleInputInvalidV2();
  }
  if (value === null || ancestors.has(value)) throw workspaceLifecycleInputInvalidV2();
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return Object.freeze(
        value.map((item) => cloneJsonValueV2(item, ancestors, depth + 1)),
      );
    }
    if (!isPlainRecordV2(value)) throw workspaceLifecycleInputInvalidV2();
    const clone: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      if (key === '__proto__' || key === 'constructor' || key === 'prototype') {
        throw workspaceLifecycleInputInvalidV2();
      }
      clone[key] = cloneJsonValueV2(item, ancestors, depth + 1);
    }
    return Object.freeze(clone);
  } finally {
    ancestors.delete(value);
  }
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function hasRequiredAndOptionalKeysV2(
  value: Record<string, unknown>,
  required: ReadonlySet<string>,
  allowed: ReadonlySet<string>,
): boolean {
  return (
    [...required].every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => allowed.has(key))
  );
}

function isCanonicalIdentifierV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isTrimmedStringV2(value: unknown): value is string {
  return typeof value === 'string' && value === value.trim();
}

function isOptionalStringV2(value: unknown): value is string | undefined {
  return value === undefined || typeof value === 'string';
}

function isOptionalCanonicalIdentifierV2(value: unknown): value is string | undefined {
  return value === undefined || isCanonicalIdentifierV2(value);
}

function isOptionalNullableStringV2(
  value: unknown,
): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function isOptionalBooleanV2(value: unknown): value is boolean | undefined {
  return value === undefined || typeof value === 'boolean';
}

function isOptionalNullableJsonRecordV2(
  value: unknown,
): value is Record<string, unknown> | null | undefined {
  if (value === undefined || value === null) return true;
  if (!isPlainRecordV2(value)) return false;
  try {
    cloneJsonRecordV2(value);
    return true;
  } catch {
    return false;
  }
}
