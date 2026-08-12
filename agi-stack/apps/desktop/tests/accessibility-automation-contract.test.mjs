import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

import {
  REQUIRED_ACCESSIBILITY_STATES,
  WCAG_22_AA_CRITERIA,
  assertCompleteAccessibilityRouteResults,
  buildCanonicalAccessibilityDataContract,
  buildCanonicalAccessibilityRouteInventory,
  buildReleaseAccessibilitySurfaceInventory,
  classifyDesktopDataStateRequest,
  deriveZoomEquivalentViewport,
  materializeAccessibilityDataPath,
  materializeAccessibilityRoutePath,
  validateCriterionLedger,
} from "../contracts/accessibility/accessibility-automation-contract.mjs";
import { auditKeyboardTraversal } from "../contracts/accessibility/playwright-keyboard-audit.mjs";
import { validateJsonSchema } from "../contracts/desktop-web-parity/schema-validator.mjs";

const CONTRACT_ROOT = new URL("../contracts/accessibility/", import.meta.url);
const PARITY_ROOT = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const routeContract = JSON.parse(
  readFileSync(new URL("web-route-inventory.v2.json", PARITY_ROOT), "utf8"),
);
const capabilityDefinitions = readdirSync(PARITY_ROOT)
  .filter((name) => /^parity-capability-definitions\.\d{2}-.+\.v2\.json$/u.test(name))
  .sort()
  .map((name) => JSON.parse(readFileSync(new URL(name, PARITY_ROOT), "utf8")));
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

test("400% zoom uses a cross-engine equivalent CSS viewport", () => {
  assert.deepEqual(
    deriveZoomEquivalentViewport({ width: 1280, height: 720 }, 4),
    {
      referenceWidth: 1280,
      referenceHeight: 720,
      zoomFactor: 4,
      width: 320,
      height: 180,
    },
  );
  assert.throws(
    () => deriveZoomEquivalentViewport({ width: 1280, height: 720 }, 0),
    /accessibility_zoom_factor_invalid/u,
  );
});

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
  const blackboard = inventory.routes.find(
    ({ routeId }) => routeId === "project-blackboard-dynamic-project-blackboard",
  );
  assert.equal(
    blackboard?.pathTemplate,
    "/tenant/:tenantId/project/:projectId/blackboard?workspaceId=:workspaceId",
  );
  assert.equal(
    materializeAccessibilityRoutePath(blackboard, {
      tenantId: "tenant / one",
      projectId: "project / one",
      workspaceId: "workspace / one",
    }),
    "/tenant/tenant%20%2F%20one/project/project%20%2F%20one/blackboard" +
      "?workspaceId=workspace%20%2F%20one",
  );
});

test("Desktop data-state audit binds every canonical route to one parity API contract", () => {
  const contract = buildCanonicalAccessibilityDataContract(
    routeContract,
    capabilityDefinitions,
  );

  assert.equal(contract.routes.length, routeContract.counts.canonical_navigation_targets);
  assert.deepEqual(
    contract.routes.map(({ routeId }) => routeId),
    routeContract.canonical_navigation_targets.map(({ route_key }) => route_key),
  );
  assert.deepEqual(
    contract.routes.find(({ routeId }) => routeId === "tenant-tenant-overview"),
    {
      routeId: "tenant-tenant-overview",
      method: "GET",
      pathTemplate: "/api/v1/tenants/{tenant_id}/stats",
    },
  );
  assert.deepEqual(
    contract.routes.find(({ routeId }) => routeId === "agent-workspace-tenant-agent-workspace"),
    {
      routeId: "agent-workspace-tenant-agent-workspace",
      method: "WS",
      pathTemplate: "/api/v1/agent/ws",
    },
  );
  assert.deepEqual(
    contract.routes.find(
      ({ routeId }) => routeId === "project-blackboard-dynamic-project-blackboard",
    ),
    {
      routeId: "project-blackboard-dynamic-project-blackboard",
      method: "GET",
      pathTemplate:
        "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/" +
        "{workspace_id}/collaboration/authority",
      injectionTrigger: "workspace-collaboration-refresh",
    },
  );
  assert.deepEqual(
    contract.routes.find(({ routeId }) => routeId === "project-project-search"),
    {
      routeId: "project-project-search",
      method: "POST",
      pathTemplate: "/api/v1/search-enhanced/advanced",
      injectionTrigger: "search-submit",
    },
  );
});

test("Desktop data-state path materialization is scope-bound and query-insensitive", () => {
  assert.equal(
    materializeAccessibilityDataPath(
      {
        routeId: "project-project-overview",
        method: "GET",
        pathTemplate: "/api/v1/projects/{project_id}?tenant_id={tenant_id}",
      },
      {
        tenantId: "tenant / one",
        projectId: "project / one",
        workspaceId: "workspace / one",
      },
    ),
    "/api/v1/projects/project%20%2F%20one",
  );
  assert.equal(
    materializeAccessibilityDataPath(
      {
        routeId: "project-blackboard-dynamic-project-blackboard",
        method: "GET",
        pathTemplate: "/api/v1/workspaces/{workspace_id}/plan",
      },
      {
        tenantId: "tenant",
        projectId: "project",
        workspaceId: "workspace",
      },
    ),
    "/api/v1/workspaces/workspace/plan",
  );
});

test("Desktop data-state contract rejects missing and duplicate canonical authority", () => {
  const missing = capabilityDefinitions.map((document) => ({
    ...document,
    capabilities: document.capabilities.filter(
      ({ id }) => id !== "tenant-tenant-overview",
    ),
  }));
  assert.throws(
    () => buildCanonicalAccessibilityDataContract(routeContract, missing),
    /accessibility_data_contract_missing:tenant-tenant-overview/u,
  );

  const duplicate = [
    ...capabilityDefinitions,
    {
      capabilities: [
        {
          id: "tenant-tenant-overview",
          api_method: "GET",
          api_path: "/api/v1/duplicate",
        },
      ],
    },
  ];
  assert.throws(
    () => buildCanonicalAccessibilityDataContract(routeContract, duplicate),
    /accessibility_data_contract_duplicate:tenant-tenant-overview/u,
  );
});

test("release accessibility inventory includes native settings, update recovery, and extension UI", () => {
  const releaseInventory = buildReleaseAccessibilitySurfaceInventory(routeContract);
  const canonicalCount = routeContract.counts.canonical_navigation_targets;

  assert.equal(releaseInventory.surfaces.web.length, canonicalCount);
  assert.equal(releaseInventory.surfaces.desktop_browser_qa.length, canonicalCount);
  assert.ok(releaseInventory.surfaces.native_electron.length > canonicalCount);
  assert.deepEqual(
    releaseInventory.surfaces.browser_extension.map(({ routeId }) => routeId),
    ["browser-extension-options", "browser-extension-sidepanel"],
  );
  assert.ok(
    releaseInventory.surfaces.native_electron.some(
      ({ routeId, launchTarget }) =>
        routeId === "native-settings-updates" &&
        launchTarget === "electron://settings/updates",
    ),
  );
  assert.ok(
    releaseInventory.surfaces.native_electron.some(
      ({ routeId, contexts }) =>
        routeId === "native-update-recovery" && contexts.includes("recovery"),
    ),
  );
});

test("Web and Desktop keyboard states use bounded traversal with focus visibility and obstruction checks", () => {
  const desktopSpec = readFileSync(
    new URL("../browser-qa/accessibility.spec.mjs", import.meta.url),
    "utf8",
  );
  const webSpec = readFileSync(
    new URL("../../../../web/e2e/wcag-aa.spec.ts", import.meta.url),
    "utf8",
  );
  const audit = readFileSync(
    new URL(
      "../contracts/accessibility/playwright-keyboard-audit.mjs",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(desktopSpec, /auditKeyboardTraversal\(page\)/u);
  assert.match(
    desktopSpec,
    /keyboard:\s*async \(\) => \{[\s\S]*waitForDesktopRouteDataBaseline\(page, route\)[\s\S]*auditKeyboardTraversal\(page\)/u,
  );
  assert.match(webSpec, /auditKeyboardTraversal\(page\)/u);
  assert.match(audit, /focusVisible/u);
  assert.match(audit, /accessibility_keyboard_focus_obscured/u);
  assert.match(audit, /Shift\+Tab/u);
});

test("keyboard traversal excludes roving controls with a negative DOM tab index", async () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  const pressed = [];
  const element = (tabIndex) => ({
    tabIndex,
    getBoundingClientRect: () => ({ width: 40, height: 24 }),
  });
  globalThis.getComputedStyle = () => ({ display: "block", visibility: "visible" });
  const page = {
    locator() {
      return {
        evaluateAll(callback) {
          return callback([element(0), element(-1)]);
        },
      };
    },
    keyboard: {
      async press(key) {
        pressed.push(key);
      },
    },
    async evaluate() {
      return {
        identity: "reachable-control",
        attached: true,
        focusVisible: true,
        visible: true,
        obscured: false,
      };
    },
  };

  try {
    const evidence = await auditKeyboardTraversal(page);
    assert.ok(evidence.includes("keyboard:focusable=1"));
    assert.deepEqual(pressed, ["Tab", "Shift+Tab"]);
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test("keyboard traversal identifies the control that loses its focus indicator", async () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  globalThis.getComputedStyle = () => ({ display: "block", visibility: "visible" });
  const page = {
    locator() {
      return {
        evaluateAll(callback) {
          return callback([
            {
              tabIndex: 0,
              getBoundingClientRect: () => ({ width: 40, height: 24 }),
            },
          ]);
        },
      };
    },
    keyboard: { async press() {} },
    async evaluate() {
      return {
        identity: "Retry",
        attached: true,
        focusVisible: false,
        visible: true,
        obscured: false,
      };
    },
  };

  try {
    await assert.rejects(
      auditKeyboardTraversal(page),
      /accessibility_keyboard_focus_indicator_missing:Retry/u,
    );
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test("keyboard traversal waits for native focus scrolling before judging visibility", async () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  const waits = [];
  const records = [
    {
      identity: "Import",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: false,
      obscured: true,
    },
    {
      identity: "Import",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: true,
      obscured: false,
    },
    {
      identity: "Import",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: true,
      obscured: false,
    },
  ];
  globalThis.getComputedStyle = () => ({ display: "block", visibility: "visible" });
  const page = {
    locator() {
      return {
        evaluateAll(callback) {
          return callback([
            { tabIndex: 0, getBoundingClientRect: () => ({ width: 40, height: 24 }) },
          ]);
        },
      };
    },
    keyboard: { async press() {} },
    async evaluate() {
      return records.shift();
    },
    async waitForTimeout(delay) {
      waits.push(delay);
    },
  };

  try {
    const evidence = await auditKeyboardTraversal(page);
    assert.ok(evidence.includes("keyboard:focus-visible=true"));
    assert.deepEqual(waits, [16]);
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test("keyboard traversal treats leaving web content as a document boundary", async () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  const pressed = [];
  const records = [
    {
      identity: "last-control",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: true,
      obscured: false,
    },
    {
      identity: "body",
      attached: true,
      documentBoundary: true,
      focusVisible: false,
      visible: true,
      obscured: false,
    },
    {
      identity: "last-control",
      attached: true,
      documentBoundary: false,
      focusVisible: true,
      visible: true,
      obscured: false,
    },
  ];
  globalThis.getComputedStyle = () => ({ display: "block", visibility: "visible" });
  const page = {
    locator() {
      return {
        evaluateAll(callback) {
          return callback([
            { tabIndex: 0, getBoundingClientRect: () => ({ width: 40, height: 24 }) },
            { tabIndex: 0, getBoundingClientRect: () => ({ width: 40, height: 24 }) },
          ]);
        },
      };
    },
    keyboard: {
      async press(key) {
        pressed.push(key);
      },
    },
    async evaluate() {
      return records.shift();
    },
  };

  try {
    const evidence = await auditKeyboardTraversal(page);
    assert.ok(evidence.includes("keyboard:steps=1"));
    assert.ok(evidence.includes("keyboard:document-boundary=true"));
    assert.deepEqual(pressed, ["Tab", "Tab", "Shift+Tab"]);
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test("Desktop canonical route failures do not cascade-skip the remaining inventory", () => {
  const desktopSpec = readFileSync(
    new URL("../browser-qa/accessibility.spec.mjs", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(
    desktopSpec,
    /test\.describe\.configure\(\{\s*mode:\s*["']serial["']/u,
  );
});

test("Web canonical route failures do not cascade-skip the remaining inventory", () => {
  const webSpec = readFileSync(
    new URL("../../../../web/e2e/wcag-aa.spec.ts", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(
    webSpec,
    /test\.describe\.configure\(\{\s*mode:\s*["']serial["']/u,
  );
});

test("Desktop accessibility QA derives role and scope from an intercepted authority boundary", () => {
  const desktopSpec = readFileSync(
    new URL("../browser-qa/accessibility.spec.mjs", import.meta.url),
    "utf8",
  );
  const authorityFixture = readFileSync(
    new URL("../browser-qa/accessibility-authority-fixture.mjs", import.meta.url),
    "utf8",
  );

  assert.match(desktopSpec, /createAccessibilityAuthorityFixture/u);
  assert.match(desktopSpec, /authorityFixture\.observation\(\)/u);
  assert.match(authorityFixture, /\/api\/v1\/auth\/token/u);
  assert.doesNotMatch(desktopSpec, /accessibilityRole/u);
  assert.doesNotMatch(desktopSpec, /data-accessibility-role/u);
  assert.match(
    desktopSpec,
    /forced-colors[\s\S]*?disabledRules:\s*\["color-contrast"\]/u,
  );
});

test("Desktop accessibility QA isolates unmodeled authority and accepts only mounted route states", () => {
  const desktopSpec = readFileSync(
    new URL("../browser-qa/accessibility.spec.mjs", import.meta.url),
    "utf8",
  );

  assert.match(desktopSpec, /accessibility_authority_fixture_unhandled/u);
  assert.doesNotMatch(
    desktopSpec,
    /resolved === null[\s\S]*?intercepted\.continue\(\)/u,
  );
  assert.match(
    desktopSpec,
    /toHaveAttribute\(\s*"data-route-state",[\s\S]*?ready\|degraded/u,
  );
  assert.match(
    desktopSpec,
    /allowMemberRouteState:\s*role === "member"/u,
  );
  assert.match(desktopSpec, /ready\|degraded\|unavailable\|forbidden/u);
});

test("Desktop data-state QA uses the canonical parity API path instead of the first background request", () => {
  const desktopSpec = readFileSync(
    new URL("../browser-qa/accessibility.spec.mjs", import.meta.url),
    "utf8",
  );

  assert.match(desktopSpec, /buildCanonicalAccessibilityDataContract/u);
  assert.match(desktopSpec, /materializeAccessibilityDataPath/u);
  assert.match(desktopSpec, /waitForDesktopRouteDataBaseline/u);
  assert.match(desktopSpec, /scope_switch/u);
  assert.doesNotMatch(
    desktopSpec,
    /exactDataPath === null[\s\S]*?pathname\.startsWith\("\/api\/v1\/"\)/u,
  );
});

test("Desktop data-state injection waits for the route surface instead of consuming capability observation", () => {
  const request = {
    method: "GET",
    exactMethod: "GET",
    pathname: "/api/v1/tenants/accessibility-tenant/stats",
    exactDataPath: "/api/v1/tenants/accessibility-tenant/stats",
  };

  assert.equal(
    classifyDesktopDataStateRequest({ ...request, routeSurfaceActive: false }),
    "authority",
  );
  assert.equal(
    classifyDesktopDataStateRequest({ ...request, routeSurfaceActive: true }),
    "inject",
  );
  assert.equal(
    classifyDesktopDataStateRequest({
      ...request,
      method: "POST",
      routeSurfaceActive: true,
    }),
    "ignore",
  );
  assert.equal(
    classifyDesktopDataStateRequest({
      ...request,
      method: "POST",
      exactMethod: "POST",
      pathname: "/api/v1/search-enhanced/advanced",
      exactDataPath: "/api/v1/search-enhanced/advanced",
      routeSurfaceActive: true,
    }),
    "inject",
  );
  assert.equal(
    classifyDesktopDataStateRequest({
      ...request,
      pathname: "/api/v1/tenants/accessibility-tenant/projects",
      routeSurfaceActive: true,
    }),
    "ignore",
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
