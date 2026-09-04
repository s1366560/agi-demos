import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectPlaybooksEventsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  listener: () => void;
}>;

export type PreparedDesktopProjectPlaybooksEventsOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  listener: () => void;
}>;

const INPUT_KEYS_V2 = new Set(['config', 'scope', 'listener']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);

export function prepareDesktopProjectPlaybooksEventsOperationV2(
  input: DesktopProjectPlaybooksEventsOperationInputV2,
): PreparedDesktopProjectPlaybooksEventsOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactKeysV2(input, INPUT_KEYS_V2) ||
    typeof input.listener !== 'function'
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({
    config: cloneDesktopProjectPlaybooksEventsConfigV2(input.config),
    scope: cloneDesktopProjectPlaybooksEventsScopeV2(input.scope, input.config),
    listener: input.listener,
  });
}

export function cloneDesktopProjectPlaybooksEventsConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidInputV2();
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
    !canonicalStringV2(copy.apiBaseUrl) ||
    !canonicalIdentifierV2(copy.tenantId) ||
    !canonicalIdentifierV2(copy.projectId)
  ) {
    throw invalidInputV2();
  }
  return Object.freeze(copy);
}

export function cloneDesktopProjectPlaybooksEventsScopeV2(
  scope: ProjectKnowledgeScope,
  config: DesktopRuntimeConfig,
): ProjectKnowledgeScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    (scope.authority !== 'cloud' && scope.authority !== 'local') ||
    !canonicalIdentifierV2(scope.tenantId) ||
    !canonicalIdentifierV2(scope.projectId) ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_playbooks_events_operation_input_invalid',
    'desktop project playbooks events operation input is invalid',
  );
}

function canonicalIdentifierV2(value: unknown): value is string {
  return (
    canonicalStringV2(value) &&
    value.length <= 256 &&
    /^[A-Za-z0-9](?:[A-Za-z0-9._:-]*[A-Za-z0-9])?$/u.test(value)
  );
}

function canonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function hasExactKeysV2(value: Record<string, unknown>, expected: ReadonlySet<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}
