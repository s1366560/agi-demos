import type {
  NativeProjectSchemaDocument as Document,
  NativeProjectSchemaScope,
} from './nativeProjectSchemaGenerated';
import {
  NATIVE_PROJECT_SCHEMA_DEFINITIONS as definitions,
  MAX_SCHEMA_DOCUMENT_BYTES,
} from './nativeProjectSchemaSchemaGenerated';
import {
  matchesSchemaDefinition,
  schemaAssert,
  utf8Length,
  plainSchemaObject,
} from './nativeProjectSchemaShape';
import { sameJson } from '../project-knowledge/nativeKnowledgeRelationships';

const limits = definitions.PortableSchemaType.properties.schema;
function weight(value: unknown): number {
  if (typeof value === 'number') return 32;
  if (Array.isArray(value))
    return (
      2 + Math.max(0, value.length - 1) + value.reduce<number>((sum, item) => sum + weight(item), 0)
    );
  if (plainSchemaObject(value))
    return (
      2 +
      Math.max(0, Object.keys(value).length - 1) +
      Object.entries(value).reduce(
        (sum, [key, child]) => sum + utf8Length(JSON.stringify(key)) + 1 + weight(child),
        0,
      )
    );
  return utf8Length(JSON.stringify(value));
}
function requireOpaque(value: unknown): void {
  let nodes = 0,
    text = 0;
  const visit = (item: unknown, depth: number): void => {
    nodes++;
    schemaAssert(nodes <= limits['x-maxNodes'] && depth <= limits['x-maxDepth']);
    if (typeof item === 'string') text += utf8Length(item);
    else if (Array.isArray(item)) item.forEach((child) => visit(child, depth + 1));
    else if (plainSchemaObject(item))
      Object.entries(item).forEach(([key, child]) => {
        text += utf8Length(key);
        visit(child, depth + 1);
      });
    schemaAssert(text <= limits['x-maxTextUtf8Bytes']);
  };
  visit(value, 0);
}
export function requireSchemaDocument(document: Document, scope: NativeProjectSchemaScope): void {
  schemaAssert(matchesSchemaDefinition('NativeProjectSchemaDocument', document));
  schemaAssert(document.tenant_id === scope.tenant_id && document.project_id === scope.project_id);
  for (const id of [document.tenant_id, document.project_id])
    schemaAssert(id.replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, '') === id);
  const all = [
    ...document.entity_types,
    ...document.edge_types,
    ...document.mappings,
    ...document.tombstones,
  ];
  schemaAssert(
    all.length <= definitions.NativeProjectSchemaDocument['x-maxTotalMembersIncludingTombstones'],
  );
  const ids = new Set([document.schema_id]);
  for (const item of all) {
    schemaAssert(!ids.has(item.id));
    ids.add(item.id);
  }
  for (const item of [...document.entity_types, ...document.edge_types]) requireOpaque(item.schema);
  const entities = new Set(document.entity_types.map((item) => item.id));
  const edges = new Set(document.edge_types.map((item) => item.id));
  for (const item of document.mappings)
    schemaAssert(
      entities.has(item.source_type_id) &&
        entities.has(item.target_type_id) &&
        edges.has(item.edge_type_id),
    );
  for (const item of document.tombstones) schemaAssert(item.deleted_revision <= document.revision);
  schemaAssert(
    utf8Length(JSON.stringify(document)) <= MAX_SCHEMA_DOCUMENT_BYTES &&
      weight(document) <= definitions.NativeProjectSchemaDocument['x-maxDocumentWeight'],
  );
}
export function canonicalSchemaDocument(document: Document): Document {
  const sorted = <T extends { readonly id: string }>(items: readonly T[]): T[] =>
    [...items].sort((a, b) => (a.id < b.id ? -1 : a.id === b.id ? 0 : 1));
  return {
    ...document,
    entity_types: sorted(document.entity_types),
    edge_types: sorted(document.edge_types),
    mappings: sorted(document.mappings),
    tombstones: sorted(document.tombstones),
  };
}
export function requireSchemaSuccessor(previous: Document | null, next: Document): void {
  schemaAssert(next.revision === (previous?.revision ?? 0) + 1);
  if (!previous) {
    schemaAssert(!next.deleted && next.tombstones.length === 0);
    return;
  }
  schemaAssert(
    !previous.deleted &&
      previous.schema_id === next.schema_id &&
      previous.tenant_id === next.tenant_id &&
      previous.project_id === next.project_id,
  );
  const live = (doc: Document) =>
    new Map([
      ...doc.entity_types.map((item) => [item.id, 'entity_type'] as const),
      ...doc.edge_types.map((item) => [item.id, 'edge_type'] as const),
      ...doc.mappings.map((item) => [item.id, 'mapping'] as const),
    ]);
  const oldLive = live(previous),
    newLive = live(next);
  const oldDead = new Map(previous.tombstones.map((item) => [item.id, item]));
  const newDead = new Map(next.tombstones.map((item) => [item.id, item]));
  for (const [id, item] of oldDead) schemaAssert(sameJson(newDead.get(id), item));
  for (const [id, kind] of newLive)
    schemaAssert(!oldDead.has(id) && (!oldLive.has(id) || oldLive.get(id) === kind));
  for (const [id, kind] of oldLive)
    schemaAssert(
      newLive.has(id) ||
        (newDead.get(id)?.kind === kind && newDead.get(id)?.deleted_revision === next.revision),
    );
  for (const [id, item] of newDead)
    schemaAssert(
      oldDead.has(id) || (oldLive.get(id) === item.kind && item.deleted_revision === next.revision),
    );
}
