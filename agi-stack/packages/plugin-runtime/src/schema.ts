import type { JsonSchemaV2 } from './generated';
import { PluginProtocolV2Error } from './errors';

const DIALECT = 'https://json-schema.org/draft/2020-12/schema';
const TYPES = ['array', 'boolean', 'integer', 'null', 'number', 'object', 'string'] as const;

export function parseContractSchemaV2(
  value: unknown,
  name: string,
  requireObject = false
): JsonSchemaV2 {
  const schema = schemaObject(value, name);
  if (schema.$schema !== DIALECT) fail(`${name} must declare JSON Schema draft 2020-12`);
  if (requireObject && schema.type !== 'object') fail(`${name} must describe an object`);
  visitMetadata(schema, name);
  validateNode(schema, name);
  return schema;
}

export function jsonSchemaValidationIssueV2(
  schema: JsonSchemaV2,
  value: unknown
): string | undefined {
  return validateValue(schema, value, schema, '$', 0);
}

function visitMetadata(value: unknown, path: string): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => visitMetadata(item, `${path}[${index}]`));
    return;
  }
  if (!isObject(value)) return;
  if ('default' in value) fail(`${path} forbids default`);
  if ('$ref' in value) {
    const reference = value.$ref;
    if (typeof reference !== 'string' || !reference.startsWith('#/')) {
      fail(`${path} forbids remote $ref`);
    }
  }
  for (const [key, child] of Object.entries(value)) visitMetadata(child, `${path}.${key}`);
}

function validateNode(schema: Record<string, unknown>, path: string): void {
  if (schema.$schema !== undefined && schema.$schema !== DIALECT) {
    fail(`${path} has an unsupported $schema`);
  }
  if (schema.type !== undefined) validateType(schema.type, `${path}.type`);
  if (schema.properties !== undefined) {
    for (const [key, child] of Object.entries(
      schemaObject(schema.properties, `${path}.properties`)
    )) {
      validateNode(schemaObject(child, `${path}.properties.${key}`), `${path}.${key}`);
    }
  }
  if (schema.required !== undefined) uniqueStrings(schema.required, `${path}.required`);
  if (
    schema.additionalProperties !== undefined &&
    typeof schema.additionalProperties !== 'boolean'
  ) {
    validateNode(
      schemaObject(schema.additionalProperties, `${path}.additionalProperties`),
      `${path}.additionalProperties`
    );
  }
  if (schema.items !== undefined) {
    validateNode(schemaObject(schema.items, `${path}.items`), `${path}.items`);
  }
  if (schema.$defs !== undefined) {
    for (const [key, child] of Object.entries(schemaObject(schema.$defs, `${path}.$defs`))) {
      validateNode(schemaObject(child, `${path}.$defs.${key}`), `${path}.$defs.${key}`);
    }
  }
  if (schema.minLength !== undefined) nonNegativeInteger(schema.minLength, `${path}.minLength`);
  if (schema.minimum !== undefined) finiteNumber(schema.minimum, `${path}.minimum`);
  if (schema.maximum !== undefined) finiteNumber(schema.maximum, `${path}.maximum`);
  if (
    typeof schema.minimum === 'number' &&
    typeof schema.maximum === 'number' &&
    schema.minimum > schema.maximum
  ) {
    fail(`${path}.minimum exceeds maximum`);
  }
  if (schema.pattern !== undefined) {
    if (typeof schema.pattern !== 'string') fail(`${path}.pattern must be a string`);
    try {
      new RegExp(schema.pattern, 'u');
    } catch {
      fail(`${path}.pattern is invalid`);
    }
  }
}

function validateType(value: unknown, name: string): void {
  if (typeof value === 'string') {
    if (!TYPES.includes(value as (typeof TYPES)[number])) fail(`${name} is unsupported`);
    return;
  }
  const types = uniqueStrings(value, name);
  if (types.length === 0 || types.some((item) => !TYPES.includes(item as (typeof TYPES)[number]))) {
    fail(`${name} has unsupported values`);
  }
}

function validateValue(
  schema: JsonSchemaV2,
  value: unknown,
  root: JsonSchemaV2,
  path: string,
  depth: number
): string | undefined {
  if (depth > 128) return `${path} exceeds schema recursion limit`;
  const reference = schema.$ref;
  if (typeof reference === 'string') {
    const resolved = resolveLocalSchema(root, reference);
    if (!resolved) return `${path} references missing schema ${reference}`;
    const issue = validateValue(resolved, value, root, path, depth + 1);
    if (issue) return issue;
  }
  if (schema.type !== undefined) {
    const types = typeof schema.type === 'string' ? [schema.type] : (schema.type as string[]);
    if (!types.some((type) => matchesType(value, type))) {
      return `${path} must be ${types.join(' or ')}`;
    }
  }
  if ('const' in schema && !jsonValuesEqual(value, schema.const)) {
    return `${path} must equal the declared const`;
  }
  const scalarIssue = validateScalar(schema, value, path);
  if (scalarIssue) return scalarIssue;
  if (Array.isArray(value) && isObject(schema.items)) {
    for (let index = 0; index < value.length; index += 1) {
      const issue = validateValue(schema.items, value[index], root, `${path}[${index}]`, depth + 1);
      if (issue) return issue;
    }
  }
  if (isObject(value)) return validateObject(schema, value, root, path, depth);
  return undefined;
}

function validateScalar(schema: JsonSchemaV2, value: unknown, path: string): string | undefined {
  if (typeof value === 'string') {
    if (typeof schema.minLength === 'number' && [...value].length < schema.minLength) {
      return `${path} must have length at least ${schema.minLength}`;
    }
    if (typeof schema.pattern === 'string' && !new RegExp(schema.pattern, 'u').test(value)) {
      return `${path} must match ${schema.pattern}`;
    }
  }
  if (typeof value === 'number') {
    if (typeof schema.minimum === 'number' && value < schema.minimum) {
      return `${path} must be at least ${schema.minimum}`;
    }
    if (typeof schema.maximum === 'number' && value > schema.maximum) {
      return `${path} must be at most ${schema.maximum}`;
    }
  }
  return undefined;
}

function validateObject(
  schema: JsonSchemaV2,
  value: Record<string, unknown>,
  root: JsonSchemaV2,
  path: string,
  depth: number
): string | undefined {
  const properties = isObject(schema.properties) ? schema.properties : {};
  const required = Array.isArray(schema.required) ? (schema.required as string[]) : [];
  for (const key of required) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) return `${path}.${key} is required`;
  }
  for (const [key, child] of Object.entries(value)) {
    const childSchema = properties[key];
    if (isObject(childSchema)) {
      const issue = validateValue(childSchema, child, root, `${path}.${key}`, depth + 1);
      if (issue) return issue;
    } else if (schema.additionalProperties === false) {
      return `${path}.${key} is not allowed`;
    } else if (isObject(schema.additionalProperties)) {
      const issue = validateValue(
        schema.additionalProperties,
        child,
        root,
        `${path}.${key}`,
        depth + 1
      );
      if (issue) return issue;
    }
  }
  return undefined;
}

function resolveLocalSchema(root: JsonSchemaV2, reference: string): JsonSchemaV2 | undefined {
  if (!reference.startsWith('#/')) return undefined;
  let current: unknown = root;
  for (const part of reference
    .slice(2)
    .split('/')
    .map((item) => item.replaceAll('~1', '/').replaceAll('~0', '~'))) {
    if (!isObject(current)) return undefined;
    current = current[part];
  }
  return isObject(current) ? current : undefined;
}

function matchesType(value: unknown, type: string): boolean {
  switch (type) {
    case 'array':
      return Array.isArray(value);
    case 'boolean':
      return typeof value === 'boolean';
    case 'integer':
      return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value);
    case 'null':
      return value === null;
    case 'number':
      return typeof value === 'number' && Number.isFinite(value);
    case 'object':
      return isObject(value);
    case 'string':
      return typeof value === 'string';
    default:
      return false;
  }
}

function jsonValuesEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length &&
      left.every((item, index) => jsonValuesEqual(item, right[index]))
    );
  }
  if (isObject(left) && isObject(right)) {
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return (
      leftKeys.length === rightKeys.length &&
      leftKeys.every(
        (key, index) => key === rightKeys[index] && jsonValuesEqual(left[key], right[key])
      )
    );
  }
  return false;
}

function schemaObject(value: unknown, name: string): Record<string, unknown> {
  if (!isObject(value)) fail(`${name} must be an object`);
  return value;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function uniqueStrings(value: unknown, name: string): string[] {
  if (!Array.isArray(value)) fail(`${name} must be an array`);
  const result = value.map((item, index) => {
    if (typeof item !== 'string' || item.length === 0) {
      fail(`${name}[${index}] must be a non-empty string`);
    }
    return item;
  });
  if (new Set(result).size !== result.length) fail(`${name} must contain unique values`);
  return result;
}

function nonNegativeInteger(value: unknown, name: string): void {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    fail(`${name} must be a non-negative integer`);
  }
}

function finiteNumber(value: unknown, name: string): void {
  if (typeof value !== 'number' || !Number.isFinite(value)) fail(`${name} must be finite`);
}

function fail(message: string): never {
  throw new PluginProtocolV2Error('invalid_contract_schema', message);
}
