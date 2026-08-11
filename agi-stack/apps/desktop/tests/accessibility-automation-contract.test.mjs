import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  REQUIRED_ACCESSIBILITY_STATES,
  WCAG_22_AA_CRITERIA,
  assertCompleteAccessibilityRouteResults,
  buildCanonicalAccessibilityRouteInventory,
  validateCriterionLedger,
} from "../contracts/accessibility/accessibility-automation-contract.mjs";
import { validateJsonSchema } from "../contracts/desktop-web-parity/schema-validator.mjs";

const CONTRACT_ROOT = new URL("../contracts/accessibility/", import.meta.url);
const PARITY_ROOT = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const routeContract = JSON.parse(
  readFileSync(new URL("web-route-inventory.v2.json", PARITY_ROOT), "utf8"),
);
const ledgerSchema = JSON.parse(
  readFileSync(
    new URL("wcag-2.2-aa-criterion-ledger.v1.schema.json", CONTRACT_ROOT),
    "utf8",
  ),
);
const ledgerTemplate = JSON.parse(
  readFileSync(
    new URL("wcag-2.2-aa-criterion-ledger.v1.template.json", CONTRACT_ROOT),
    "utf8",
  ),
);

test("accessibility inventory derives every canonical route without hand-maintained omissions", () => {
  const inventory = buildCanonicalAccessibilityRouteInventory(routeContract);
  const expectedIds = routeContract.canonical_navigation_targets.map(
    ({ route_key }) => route_key,
  );

  assert.equal(inventory.sourceRevision, routeContract.source_revision);
  assert.equal(
    inventory.routes.length,
    routeContract.counts.canonical_navigation_targets,
  );
  assert.deepEqual(
    inventory.routes.map(({ routeId }) => routeId),
    expectedIds,
  );
  assert.equal(
    inventory.routes.find(({ routeId }) => routeId === "tenant-tenant-overview")
      ?.pathTemplate,
    "/tenant/:tenantId/overview",
  );
  assert.equal(
    inventory.routes.find(({ routeId }) => routeId === "project-agent-logs")
      ?.pathTemplate,
    "/tenant/:tenantId/project/:projectId/agent/logs",
  );
});

test("accessibility route gate fails closed on missing, duplicate, or early-returned state evidence", () => {
  const inventory = buildCanonicalAccessibilityRouteInventory(routeContract);
  assert.deepEqual(REQUIRED_ACCESSIBILITY_STATES, [
    "default",
    "keyboard",
    "text-zoom-200",
    "reflow-320",
    "zoom-400",
    "reduced-motion",
    "forced-colors",
    "theme-light",
    "theme-dark",
    "locale-en-US",
    "locale-zh-CN",
    "role-admin",
    "role-member",
    "data-loading",
    "data-empty",
    "data-forbidden",
    "data-error",
    "data-conflict",
  ]);
  const complete = inventory.routes.map(({ routeId }) => ({
    routeId,
    states: REQUIRED_ACCESSIBILITY_STATES.map((stateId) => ({
      stateId,
      status: "passed",
      evidence: [`artifact:${routeId}:${stateId}`],
    })),
  }));

  assert.doesNotThrow(() =>
    assertCompleteAccessibilityRouteResults(inventory, complete),
  );
  assert.throws(
    () => assertCompleteAccessibilityRouteResults(inventory, complete.slice(1)),
    /accessibility_route_missing:/u,
  );
  assert.throws(
    () =>
      assertCompleteAccessibilityRouteResults(inventory, [
        ...complete,
        complete[0],
      ]),
    /accessibility_route_duplicate:/u,
  );
  assert.throws(
    () =>
      assertCompleteAccessibilityRouteResults(inventory, [
        { ...complete[0], states: complete[0].states.slice(0, -1) },
        ...complete.slice(1),
      ]),
    /accessibility_state_missing:.*data-conflict/u,
  );
  assert.throws(
    () =>
      assertCompleteAccessibilityRouteResults(inventory, [
        {
          ...complete[0],
          states: complete[0].states.map((state) =>
            state.stateId === "keyboard"
              ? { stateId: "keyboard", status: "not_run", evidence: [] }
              : state,
          ),
        },
        ...complete.slice(1),
      ]),
    /accessibility_state_not_executed:.*keyboard:not_run/u,
  );
});

test("WCAG 2.2 AA ledger template is schema-valid and explicitly not executed", () => {
  assert.deepEqual(validateJsonSchema(ledgerSchema, ledgerTemplate), []);
  assert.deepEqual(
    ledgerTemplate.criteria.map(({ criterion_id }) => criterion_id),
    WCAG_22_AA_CRITERIA.map(({ id }) => id),
  );
  for (const defaults of Object.values(ledgerTemplate.assessment_defaults)) {
    assert.ok(["not_run", "blocked"].includes(defaults.status));
  }
  assert.deepEqual(Object.keys(ledgerTemplate.assessment_defaults).sort(), [
    "browser_extension",
    "desktop_browser_qa",
    "native_electron",
    "web",
  ]);
  assert.deepEqual(
    ledgerTemplate.route_coverage.map(({ surface }) => surface).sort(),
    ["browser_extension", "desktop_browser_qa", "native_electron", "web"],
  );
  assert.ok(
    ledgerTemplate.criteria.every(
      ({ methods }) => methods.browser_extension !== undefined,
    ),
  );
  assert.deepEqual(
    validateCriterionLedger(ledgerTemplate, { allowTemplate: true }),
    [],
  );
});

test("criterion ledger accepts judgment-bound manual AT evidence and rejects forged passes", () => {
  const manualPass = structuredClone(ledgerTemplate);
  manualPass.record_kind = "evidence";
  manualPass.source_revision = "a".repeat(40);
  manualPass.generated_at = "2026-08-11T00:00:00.000Z";
  manualPass.assessments.push({
    criterion_id: manualPass.criteria[0].criterion_id,
    surface: "native_electron",
    method: "manual_at",
    status: "passed",
    evidence: ["artifact:claimed-screen-reader-pass"],
    blocker_reason: null,
    judgment: null,
  });
  assert.match(
    validateCriterionLedger(manualPass, { allowTemplate: true }).join("\n"),
    /manual_at.*structured judgment/u,
  );

  manualPass.assessments[0].judgment = {
    agent_id: "wcag-review-agent",
    tool_name: "record_accessibility_judgment",
    input_ref: "artifact:voiceover-electron-core-journey",
    output: "accepted",
    rationale: "VoiceOver announced the control name, role, value, and changed state.",
    latency_ms: 842,
    revision: manualPass.source_revision,
  };
  assert.doesNotMatch(
    validateCriterionLedger(manualPass, { allowTemplate: true }).join("\n"),
    /manual_at.*structured judgment/u,
  );

  const automatedPass = structuredClone(ledgerTemplate);
  automatedPass.assessments.push({
    criterion_id: automatedPass.criteria[0].criterion_id,
    surface: "web",
    method: "axe",
    status: "passed",
    evidence: [],
    blocker_reason: null,
    judgment: null,
  });
  assert.match(
    validateCriterionLedger(automatedPass, { allowTemplate: true }).join("\n"),
    /passed assessment requires evidence/u,
  );
});
