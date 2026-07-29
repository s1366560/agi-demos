import assert from "node:assert/strict";
import { test } from "node:test";

import { validateJsonSchema } from "../contracts/desktop-web-parity/schema-validator.mjs";

test("schema validator enforces numeric and object cardinality keywords", () => {
  assert.deepEqual(
    validateJsonSchema({ type: "number", exclusiveMinimum: 0 }, 0),
    ["$ must be greater than 0"],
  );
  assert.deepEqual(
    validateJsonSchema({ type: "number", exclusiveMinimum: 0 }, -1),
    ["$ must be greater than 0"],
  );
  assert.deepEqual(
    validateJsonSchema({ type: "number", exclusiveMinimum: 0 }, 0.1),
    [],
  );
  assert.deepEqual(
    validateJsonSchema({ type: "object", minProperties: 1 }, {}),
    ["$ must contain at least 1 properties"],
  );
  assert.deepEqual(
    validateJsonSchema({ type: "object", minProperties: 1 }, { input: true }),
    [],
  );
});

test("schema validator enforces deep uniqueItems semantics", () => {
  const schema = {
    type: "array",
    uniqueItems: true,
    items: {
      type: "object",
      required: ["id"],
      properties: { id: { type: "string" } },
      additionalProperties: false,
    },
  };

  assert.deepEqual(validateJsonSchema(schema, [{ id: "a" }, { id: "b" }]), []);
  assert.deepEqual(validateJsonSchema(schema, [{ id: "a" }, { id: "a" }]), [
    "$ must contain unique items; duplicate indexes 0 and 1",
  ]);
});

test("schema validator enforces not branches", () => {
  const schema = {
    type: "object",
    not: { required: ["route_contract"] },
  };

  assert.deepEqual(validateJsonSchema(schema, {}), []);
  assert.deepEqual(
    validateJsonSchema(schema, { route_contract: "unexpected" }),
    ["$ must not satisfy the excluded schema"],
  );
});
