import { NATIVE_PROJECT_SCHEMA_DEFINITIONS } from './nativeProjectSchemaSchemaGenerated';
import { projectKnowledgeError } from '../project-knowledge/projectKnowledgeClient';

type Schema = Readonly<Record<string, unknown>>;
const definitions: Readonly<Record<string, Schema>> = NATIVE_PROJECT_SCHEMA_DEFINITIONS;
const encoder = new TextEncoder();
export const schemaInvalid = (): never => {
  throw projectKnowledgeError('native_project_schema_contract_invalid', 422);
};
export function schemaAssert(value: unknown): asserts value {
  if (!value) schemaInvalid();
}
export function plainSchemaObject(value: unknown): value is Record<string, unknown> {
  return (
    value !== null &&
    typeof value === 'object' &&
    (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
  );
}
export function utf8Length(value: string): number {
  return encoder.encode(value).length;
}

/** Snapshot caller-owned data without executing accessors, toJSON, or retaining aliases. */
export function freezeSchemaJson<T>(input: T, limit = 2 * 1024 * 1024): T {
  let bytes = 0;
  const ancestors = new Set<object>();
  const charge = (count: number) => {
    bytes += count;
    schemaAssert(bytes <= limit);
  };
  const visit = (value: unknown, depth: number): unknown => {
    schemaAssert(depth <= 30);
    if (value === null || typeof value === 'boolean') {
      charge(value === false ? 5 : 4);
      return value;
    }
    if (typeof value === 'number') {
      schemaAssert(Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER);
      charge(JSON.stringify(value).length);
      return value;
    }
    if (typeof value === 'string') {
      schemaAssert(value.length <= limit);
      for (let i = 0; i < value.length; i++) {
        const code = value.charCodeAt(i);
        if (code >= 0xd800 && code <= 0xdbff) {
          const next = value.charCodeAt(++i);
          schemaAssert(next >= 0xdc00 && next <= 0xdfff);
        } else schemaAssert(code < 0xdc00 || code > 0xdfff);
      }
      charge(utf8Length(JSON.stringify(value)));
      return value;
    }
    schemaAssert(Array.isArray(value) || plainSchemaObject(value));
    const object = value as object;
    schemaAssert(!ancestors.has(object));
    ancestors.add(object);
    const descriptors = Object.getOwnPropertyDescriptors(object);
    schemaAssert(Object.getOwnPropertySymbols(object).length === 0);
    charge(2);
    let result: unknown;
    if (Array.isArray(value)) {
      schemaAssert(Object.keys(descriptors).length === value.length + 1);
      const items: unknown[] = [];
      for (let i = 0; i < value.length; i++) {
        const descriptor = descriptors[String(i)];
        schemaAssert(descriptor && 'value' in descriptor && descriptor.enumerable);
        if (i) charge(1);
        items.push(visit(descriptor.value, depth + 1));
      }
      result = Object.freeze(items);
    } else {
      const entries: [string, unknown][] = [];
      for (const [key, descriptor] of Object.entries(descriptors)) {
        schemaAssert('value' in descriptor && descriptor.enumerable);
        if (entries.length) charge(1);
        visit(key, depth + 1);
        charge(1);
        entries.push([key, visit(descriptor.value, depth + 1)]);
      }
      result = Object.freeze(Object.fromEntries(entries));
    }
    ancestors.delete(object);
    return result;
  };
  return visit(input, 0) as T;
}

/** Only generated repository-owned schemas are interpreted; document.schema stays opaque data. */
export function matchesSchemaDefinition(name: string, value: unknown): boolean {
  const root = definitions[name];
  schemaAssert(root);
  return matches(root, value);
}
function matches(schema: Schema, value: unknown): boolean {
  if (typeof schema.$ref === 'string') {
    const reference = definitions[schema.$ref.replace('#/$defs/', '')];
    return !!reference && matches(reference, value);
  }
  if ('const' in schema && value !== schema.const) return false;
  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) return false;
  if (Array.isArray(schema.anyOf) && !schema.anyOf.some((part: Schema) => matches(part, value)))
    return false;
  if (Array.isArray(schema.allOf) && !schema.allOf.every((part: Schema) => matches(part, value)))
    return false;
  if (schema.not && matches(schema.not as Schema, value)) return false;
  if (
    schema.if &&
    matches(schema.if as Schema, value) &&
    schema.then &&
    !matches(schema.then as Schema, value)
  )
    return false;
  switch (schema.type) {
    case 'null':
      if (value !== null) return false;
      break;
    case 'boolean':
      if (typeof value !== 'boolean') return false;
      break;
    case 'string':
      if (typeof value !== 'string') return false;
      break;
    case 'integer':
      if (!Number.isSafeInteger(value)) return false;
      break;
    case 'number':
      if (typeof value !== 'number' || !Number.isFinite(value)) return false;
      break;
    case 'array':
      if (!Array.isArray(value)) return false;
      break;
    case 'object':
      if (!plainSchemaObject(value)) return false;
      break;
  }
  if (
    typeof value === 'number' &&
    ((typeof schema.minimum === 'number' && value < schema.minimum) ||
      (typeof schema.maximum === 'number' && value > schema.maximum))
  )
    return false;
  if (typeof value === 'string') {
    if (typeof schema.minLength === 'number' && [...value].length < schema.minLength) return false;
    if (typeof schema.maxLength === 'number' && [...value].length > schema.maxLength) return false;
    if (
      typeof schema['x-maxUtf8Bytes'] === 'number' &&
      utf8Length(value) > schema['x-maxUtf8Bytes']
    )
      return false;
    if (typeof schema.pattern === 'string' && !new RegExp(schema.pattern, 'u').test(value))
      return false;
  }
  if (Array.isArray(value)) {
    if (typeof schema.maxItems === 'number' && value.length > schema.maxItems) return false;
    if (schema.items && !value.every((item) => matches(schema.items as Schema, item))) return false;
  }
  if (plainSchemaObject(value)) {
    if (
      Array.isArray(schema.required) &&
      !schema.required.every((key: string) => Object.hasOwn(value, key))
    )
      return false;
    const properties = (schema.properties ?? {}) as Readonly<Record<string, Schema>>;
    for (const [key, item] of Object.entries(value)) {
      if (schema.propertyNames && !matches(schema.propertyNames as Schema, key)) return false;
      if (Object.hasOwn(properties, key)) {
        if (!matches(properties[key]!, item)) return false;
      } else if (schema.additionalProperties === false) return false;
      else if (
        plainSchemaObject(schema.additionalProperties) &&
        !matches(schema.additionalProperties, item)
      )
        return false;
    }
  }
  return true;
}
