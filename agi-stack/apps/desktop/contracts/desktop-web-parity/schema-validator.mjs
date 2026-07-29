import { isDeepStrictEqual } from 'node:util';

function valueType(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  return typeof value;
}

function matchesType(expected, value) {
  const actual = valueType(value);
  const allowed = Array.isArray(expected) ? expected : [expected];
  return allowed.includes(actual);
}

export function validateJsonSchema(schema, value, path = '$', rootSchema = schema) {
  const errors = [];

  if (schema.$ref) {
    const resolved = resolveLocalReference(rootSchema, schema.$ref);
    return resolved
      ? validateJsonSchema(resolved, value, path, rootSchema)
      : [`${path} references an unknown schema ${schema.$ref}`];
  }

  if (schema.type && !matchesType(schema.type, value)) {
    return [`${path} must be ${JSON.stringify(schema.type)}; received ${valueType(value)}`];
  }

  if (Object.hasOwn(schema, 'const') && !Object.is(value, schema.const)) {
    errors.push(`${path} must equal ${JSON.stringify(schema.const)}`);
  }
  if (schema.enum && !schema.enum.some((candidate) => Object.is(candidate, value))) {
    errors.push(`${path} must be one of ${schema.enum.map((item) => JSON.stringify(item)).join(', ')}`);
  }

  if (typeof value === 'string') {
    if (schema.minLength !== undefined && value.length < schema.minLength) {
      errors.push(`${path} must contain at least ${schema.minLength} characters`);
    }
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) {
      errors.push(`${path} must match ${schema.pattern}`);
    }
  }

  if (typeof value === 'number' && schema.minimum !== undefined && value < schema.minimum) {
    errors.push(`${path} must be at least ${schema.minimum}`);
  }
  if (
    typeof value === 'number' &&
    schema.exclusiveMinimum !== undefined &&
    value <= schema.exclusiveMinimum
  ) {
    errors.push(`${path} must be greater than ${schema.exclusiveMinimum}`);
  }

  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) {
      errors.push(`${path} must contain at least ${schema.minItems} items`);
    }
    if (schema.maxItems !== undefined && value.length > schema.maxItems) {
      errors.push(`${path} must contain at most ${schema.maxItems} items`);
    }
    if (schema.uniqueItems === true) {
      for (let left = 0; left < value.length; left += 1) {
        for (let right = left + 1; right < value.length; right += 1) {
          if (isDeepStrictEqual(value[left], value[right])) {
            errors.push(
              `${path} must contain unique items; duplicate indexes ${left} and ${right}`,
            );
          }
        }
      }
    }
    if (schema.items) {
      value.forEach((item, index) => {
        errors.push(
          ...validateJsonSchema(schema.items, item, `${path}[${index}]`, rootSchema),
        );
      });
    }
  }

  if (value && typeof value === 'object' && !Array.isArray(value)) {
    if (
      schema.minProperties !== undefined &&
      Object.keys(value).length < schema.minProperties
    ) {
      errors.push(
        `${path} must contain at least ${schema.minProperties} properties`,
      );
    }
    for (const required of schema.required ?? []) {
      if (!Object.hasOwn(value, required)) {
        errors.push(`${path}.${required} is required`);
      }
    }
    for (const [key, child] of Object.entries(value)) {
      const childSchema = schema.properties?.[key];
      if (childSchema) {
        errors.push(
          ...validateJsonSchema(childSchema, child, `${path}.${key}`, rootSchema),
        );
      } else if (schema.additionalProperties === false) {
        errors.push(`${path}.${key} is not allowed`);
      }
    }
  }

  if (schema.oneOf) {
    const alternatives = schema.oneOf.map((candidate) =>
      validateJsonSchema(candidate, value, path, rootSchema),
    );
    const matches = alternatives.filter((candidateErrors) => candidateErrors.length === 0);
    if (matches.length !== 1) {
      errors.push(`${path} must satisfy exactly one oneOf branch`);
      if (matches.length === 0) {
        errors.push(...alternatives.flat());
      }
    }
  }

  if (
    schema.not &&
    validateJsonSchema(schema.not, value, path, rootSchema).length === 0
  ) {
    errors.push(`${path} must not satisfy the excluded schema`);
  }

  return errors;
}

function resolveLocalReference(rootSchema, reference) {
  if (typeof reference !== 'string' || !reference.startsWith('#/')) return null;
  let current = rootSchema;
  for (const encodedSegment of reference.slice(2).split('/')) {
    const segment = encodedSegment.replaceAll('~1', '/').replaceAll('~0', '~');
    if (
      current === null ||
      typeof current !== 'object' ||
      Array.isArray(current) ||
      !Object.hasOwn(current, segment)
    ) {
      return null;
    }
    current = current[segment];
  }
  return current;
}
