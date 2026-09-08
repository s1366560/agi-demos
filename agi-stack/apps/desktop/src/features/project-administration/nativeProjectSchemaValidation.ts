import type * as K from './nativeProjectSchemaGenerated';
import {
  NATIVE_PROJECT_SCHEMA_ACTIONS as actions,
  MAX_SCHEMA_REQUEST_BYTES,
  MAX_SCHEMA_RESPONSE_BYTES,
} from './nativeProjectSchemaSchemaGenerated';
import {
  freezeSchemaJson,
  matchesSchemaDefinition,
  schemaAssert,
  utf8Length,
} from './nativeProjectSchemaShape';
import {
  canonicalSchemaDocument,
  requireSchemaDocument,
  requireSchemaSuccessor,
} from './nativeProjectSchemaDocument';
import { sameJson } from '../project-knowledge/nativeKnowledgeRelationships';

export function prepareNativeProjectSchemaRequest<A extends K.NativeProjectSchemaAction>(
  action: A,
  input: K.NativeProjectSchemaRequestMap[A],
): K.NativeProjectSchemaRequestMap[A] {
  schemaAssert(Object.hasOwn(actions, action));
  const request = freezeSchemaJson(input, MAX_SCHEMA_REQUEST_BYTES);
  schemaAssert(matchesSchemaDefinition(actions[action].request, request));
  if ('document' in request) {
    requireSchemaDocument(request.document, request.scope);
    schemaAssert(request.document.revision === request.expected_revision + 1);
    if (action === 'schema_bootstrap') requireSchemaSuccessor(null, request.document);
  }
  return request;
}
function requireReceipt(
  receipt: K.NativeProjectSchemaReceipt,
  scope: K.NativeProjectSchemaScope,
): void {
  requireSchemaDocument(receipt.document, scope);
  schemaAssert(receipt.sequence === receipt.document.revision);
  schemaAssert(sameJson(receipt.document, canonicalSchemaDocument(receipt.document)));
  if (receipt.sequence === 1) requireSchemaSuccessor(null, receipt.document);
}
export function requireNativeProjectSchemaResponse<A extends K.NativeProjectSchemaAction>(
  action: A,
  input: unknown,
  request: K.NativeProjectSchemaRequestMap[A],
  actor: string,
): K.NativeProjectSchemaResponseMap[A] {
  schemaAssert(Object.hasOwn(actions, action));
  const response = freezeSchemaJson(
    input,
    MAX_SCHEMA_RESPONSE_BYTES,
  ) as K.NativeProjectSchemaResponseMap[A];
  schemaAssert(matchesSchemaDefinition(actions[action].response, response));
  schemaAssert(response.actor_id === actor && sameJson(response.scope, request.scope));
  const result = response.result;
  if ('document' in result && result.document !== null) {
    requireSchemaDocument(result.document, request.scope);
    if (result.document.revision === 1) requireSchemaSuccessor(null, result.document);
    schemaAssert(sameJson(result.document, canonicalSchemaDocument(result.document)));
  }
  if ('receipt' in result && result.receipt !== null) {
    requireReceipt(result.receipt, request.scope);
    schemaAssert(
      'change_id' in request &&
        result.receipt.change_id === request.change_id &&
        result.receipt.actor_id === actor,
    );
    if ('document' in request)
      schemaAssert(
        sameJson(result.receipt.document, canonicalSchemaDocument(request.document)) &&
          result.receipt.sequence === request.expected_revision + 1,
      );
  }
  if ('items' in result) {
    schemaAssert(
      'after_revision' in request &&
        result.after_revision === request.after_revision &&
        result.items.length <= request.limit,
    );
    schemaAssert(
      result.after_revision <= result.upper_revision &&
        result.next_after_revision <= result.upper_revision,
    );
    schemaAssert(
      result.next_after_revision === (result.items.at(-1)?.sequence ?? result.after_revision),
    );
    schemaAssert(result.has_more === result.next_after_revision < result.upper_revision);
    schemaAssert(!result.has_more || result.items.length > 0);
    if (result.schema_id === null)
      schemaAssert(
        result.upper_revision === 0 && result.after_revision === 0 && result.items.length === 0,
      );
    else schemaAssert(result.upper_revision > 0);
    const changes = new Set<string>();
    for (const [index, item] of result.items.entries()) {
      const key = JSON.stringify([item.actor_id, item.change_id]);
      schemaAssert(!changes.has(key));
      changes.add(key);
      schemaAssert(!item.document.deleted || item.sequence === result.upper_revision);
      requireReceipt(item, request.scope);
      schemaAssert(
        item.document.schema_id === result.schema_id &&
          item.sequence === result.after_revision + index + 1,
      );
      if (index > 0) requireSchemaSuccessor(result.items[index - 1]!.document, item.document);
    }
  }
  return response;
}
export function requireNativeProjectSchemaCapabilities(
  input: unknown,
  scope: K.NativeProjectSchemaScope,
  actor: string,
): K.NativeProjectSchemaCapabilitiesResponse {
  const response = freezeSchemaJson(input) as K.NativeProjectSchemaCapabilitiesResponse;
  schemaAssert(matchesSchemaDefinition('NativeProjectSchemaCapabilitiesResponse', response));
  schemaAssert(response.actor_id === actor && sameJson(response.scope, scope));
  const allowed = response.result.allowed_actions;
  schemaAssert(new Set(allowed).size === allowed.length);
  schemaAssert((response.result.availability === 'unavailable') === (allowed.length === 0));
  schemaAssert(utf8Length(actor) <= 512 && actor.length > 0);
  return response;
}
