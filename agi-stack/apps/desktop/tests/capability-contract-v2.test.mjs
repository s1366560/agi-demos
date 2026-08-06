import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { normalizeDesktopParityFixture } from "../contracts/desktop-web-parity/desktop-normalizer.mjs";
import { validateJsonSchema } from "../contracts/desktop-web-parity/schema-validator.mjs";
import { normalizeWebParityFixture } from "../contracts/desktop-web-parity/web-normalizer.mjs";

const require = createRequire(import.meta.url);
const {
  desktopCapability,
  parseDesktopCapabilitySnapshot,
} = require("/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js");
const {
  negotiateCapabilityContract,
} = require("/tmp/agistack-desktop-test-dist/src/features/runtime/capabilityVersion.js");
const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const nullScope = {
  tenant_id: null,
  project_id: null,
  workspace_id: null,
  instance_id: null,
};

function readJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), "utf8"));
}

test("DesktopCapabilitySnapshot v2 remains a validated read-only input contract", () => {
  const fixture = readJson("fixtures/capability-snapshot.v2.json");
  const fixtureSchema = readJson("parity-fixture.v2.schema.json");
  const schema = readJson("desktop-capability-snapshot.v2.schema.json");

  assert.deepEqual(validateJsonSchema(fixtureSchema, fixture), []);
  assert.deepEqual(validateJsonSchema(schema, fixture.input.snapshot), []);
  const snapshot = parseDesktopCapabilitySnapshot(fixture.input.snapshot);
  assert.equal(snapshot?.version, "4.0.0");
  assert.deepEqual(desktopCapability(snapshot, "search"), {
    availability: "degraded",
    reason_code: "local_search_keyword_only",
    service_version: "0.1.0",
    contract_version: "2.0.0",
    allowed_actions: [],
    scope: nullScope,
    authority_revision: null,
    authority_source: "renderer",
    provenance: "declared",
    status: "degraded",
    available: false,
  });
  assert.deepEqual(desktopCapability(snapshot, "sandbox_isolation"), {
    availability: "not_applicable",
    reason_code: "local_isolation_not_applicable",
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope: nullScope,
    authority_revision: null,
    authority_source: "renderer",
    provenance: "declared",
    status: "not_applicable",
    available: false,
  });

  const input = { kind: fixture.kind, input: fixture.input };
  assert.deepEqual(
    normalizeWebParityFixture(input),
    fixture.web_expected_view_model,
  );
  assert.deepEqual(
    normalizeDesktopParityFixture(input),
    fixture.desktop_expected_view_model,
  );
});

test("DesktopCapabilitySnapshot v2 rejects legacy and internally inconsistent snapshots", () => {
  const legacy = readJson("fixtures/capability-snapshot.v1.json");
  assert.equal(parseDesktopCapabilitySnapshot(legacy.input.snapshot), null);

  const fixture = readJson("fixtures/capability-snapshot.v2.json");
  const availableWithReason = structuredClone(fixture.input.snapshot);
  availableWithReason.capabilities.search.status = "available";
  assert.equal(parseDesktopCapabilitySnapshot(availableWithReason), null);

  const degradedWithoutServiceVersion = structuredClone(fixture.input.snapshot);
  degradedWithoutServiceVersion.capabilities.search.service_version = null;
  assert.equal(
    parseDesktopCapabilitySnapshot(degradedWithoutServiceVersion),
    null,
  );

  const unstableReason = structuredClone(fixture.input.snapshot);
  unstableReason.capabilities.search.reason_code = "HTTP 404";
  assert.equal(parseDesktopCapabilitySnapshot(unstableReason), null);
});

test("capability contract negotiation accepts compatible versions and fails old services closed", () => {
  assert.deepEqual(
    negotiateCapabilityContract(
      { service_version: "0.1.0", contract_version: "2.3.0" },
      "2.0.0",
    ),
    {
      compatible: true,
      reason_code: null,
      service_version: "0.1.0",
      contract_version: "2.3.0",
      minimum_contract_version: "2.0.0",
    },
  );
  assert.deepEqual(negotiateCapabilityContract({}, "2.0.0"), {
    compatible: false,
    reason_code: "capability_contract_version_missing",
    service_version: null,
    contract_version: null,
    minimum_contract_version: "2.0.0",
  });
  assert.deepEqual(
    negotiateCapabilityContract(
      { service_version: "0.1.0", contract_version: "1.9.0" },
      "2.0.0",
    ),
    {
      compatible: false,
      reason_code: "capability_contract_version_too_old",
      service_version: "0.1.0",
      contract_version: "1.9.0",
      minimum_contract_version: "2.0.0",
    },
  );
  assert.deepEqual(
    negotiateCapabilityContract(
      { service_version: "0.1.0", contract_version: "3.0.0" },
      "2.0.0",
    ),
    {
      compatible: false,
      reason_code: "capability_contract_version_unsupported",
      service_version: "0.1.0",
      contract_version: "3.0.0",
      minimum_contract_version: "2.0.0",
    },
  );
});
