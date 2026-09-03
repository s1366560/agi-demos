import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  PROJECT_GRAPH_DEGRADED_REASON,
  type ProjectGraphEdge,
  type ProjectGraphNode,
  type ProjectGraphSnapshot,
} from '../features/project-knowledge/projectGraphClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectGraphOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  signal?: AbortSignal;
}>;

export type PreparedDesktopProjectGraphOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  signal?: AbortSignal;
}>;

const INPUT_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'scopeRevision',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'nodes',
  'edges',
]);
const NODE_KEYS_V2 = new Set(['id', 'label', 'type', 'name', 'summary']);
const EDGE_KEYS_V2 = new Set(['id', 'source', 'target', 'label', 'weight']);
const NODE_TYPES_V2 = new Set<ProjectGraphNode['type']>([
  'Entity',
  'Episodic',
  'Community',
]);

export function prepareDesktopProjectGraphOperationV2(
  input: DesktopProjectGraphOperationInputV2,
): PreparedDesktopProjectGraphOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasAllowedKeysV2(input, INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidInputV2();
  }
  const config = cloneDesktopProjectGraphRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectGraphScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectGraphRuntimeConfigV2(
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

export function cloneDesktopProjectGraphScopeV2(
  scope: ProjectKnowledgeScope,
  config: DesktopRuntimeConfig,
): ProjectKnowledgeScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    scope.authority !== config.mode ||
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

export function requireDesktopProjectGraphSnapshotV2(
  value: unknown,
  scope: ProjectKnowledgeScope,
): ProjectGraphSnapshot {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== scope.authority ||
    value.availability !== 'degraded' ||
    value.reasonCode !== PROJECT_GRAPH_DEGRADED_REASON ||
    !exactViewActionsV2(value.allowedActions) ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    !sameScopeV2(value.scope, scope) ||
    !validGraphV2(value.nodes, value.edges)
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as ProjectGraphSnapshot;
}

function validGraphV2(nodesValue: unknown, edgesValue: unknown): boolean {
  if (!Array.isArray(nodesValue) || !Array.isArray(edgesValue)) return false;
  const nodeIds = new Set<string>();
  for (const node of nodesValue) {
    if (!validNodeV2(node) || nodeIds.has(node.id)) return false;
    nodeIds.add(node.id);
  }
  const edgeIds = new Set<string>();
  for (const edge of edgesValue) {
    if (
      !validEdgeV2(edge) ||
      edgeIds.has(edge.id) ||
      !nodeIds.has(edge.source) ||
      !nodeIds.has(edge.target)
    ) {
      return false;
    }
    edgeIds.add(edge.id);
  }
  return true;
}

function validNodeV2(value: unknown): value is ProjectGraphNode {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, NODE_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    typeof value.label === 'string' &&
    typeof value.type === 'string' &&
    NODE_TYPES_V2.has(value.type as ProjectGraphNode['type']) &&
    canonicalIdentifierV2(value.name) &&
    (value.summary === null || typeof value.summary === 'string')
  );
}

function validEdgeV2(value: unknown): value is ProjectGraphEdge {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, EDGE_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    canonicalIdentifierV2(value.source) &&
    canonicalIdentifierV2(value.target) &&
    typeof value.label === 'string' &&
    (value.weight === null ||
      (typeof value.weight === 'number' && Number.isFinite(value.weight)))
  );
}

function sameScopeV2(value: unknown, scope: ProjectKnowledgeScope): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, SCOPE_KEYS_V2) &&
    value.authority === scope.authority &&
    value.tenantId === scope.tenantId &&
    value.projectId === scope.projectId
  );
}

function exactViewActionsV2(value: unknown): boolean {
  return Array.isArray(value) && value.length === 1 && value[0] === 'view';
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_graph_operation_input_invalid',
    'desktop project graph operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_graph_service_contract_invalid',
    'desktop project graph authority returned an invalid result',
  );
}

function hasAllowedKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function canonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function canonicalIdentifierV2(value: unknown): value is string {
  return canonicalStringV2(value) && value.length <= 512;
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}

function deepFreezeV2<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const nested of Object.values(value)) deepFreezeV2(nested);
  }
  return value;
}
