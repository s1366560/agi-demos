import { readFileSync } from "node:fs";

import { validateJsonSchema } from "../desktop-web-parity/schema-validator.mjs";

const CONTRACT_ROOT = new URL("./", import.meta.url);
const LEDGER_SCHEMA = JSON.parse(
  readFileSync(
    new URL("wcag-2.2-aa-criterion-ledger.v1.schema.json", CONTRACT_ROOT),
    "utf8",
  ),
);
const SURFACES = Object.freeze([
  "web",
  "desktop_browser_qa",
  "browser_extension",
  "native_electron",
]);
const EXECUTED_STATUSES = new Set(["passed", "failed"]);

export const REQUIRED_ACCESSIBILITY_STATES = Object.freeze([
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

export const WCAG_22_AA_CRITERIA = Object.freeze([
  criterion("1.1.1", "A", "Non-text Content"),
  criterion("1.2.1", "A", "Audio-only and Video-only (Prerecorded)"),
  criterion("1.2.2", "A", "Captions (Prerecorded)"),
  criterion(
    "1.2.3",
    "A",
    "Audio Description or Media Alternative (Prerecorded)",
  ),
  criterion("1.2.4", "AA", "Captions (Live)"),
  criterion("1.2.5", "AA", "Audio Description (Prerecorded)"),
  criterion("1.3.1", "A", "Info and Relationships"),
  criterion("1.3.2", "A", "Meaningful Sequence"),
  criterion("1.3.3", "A", "Sensory Characteristics"),
  criterion("1.3.4", "AA", "Orientation"),
  criterion("1.3.5", "AA", "Identify Input Purpose"),
  criterion("1.4.1", "A", "Use of Color"),
  criterion("1.4.2", "A", "Audio Control"),
  criterion("1.4.3", "AA", "Contrast (Minimum)"),
  criterion("1.4.4", "AA", "Resize Text", "state_contract"),
  criterion("1.4.5", "AA", "Images of Text"),
  criterion("1.4.10", "AA", "Reflow", "state_contract"),
  criterion("1.4.11", "AA", "Non-text Contrast"),
  criterion("1.4.12", "AA", "Text Spacing"),
  criterion("1.4.13", "AA", "Content on Hover or Focus"),
  criterion("2.1.1", "A", "Keyboard", "state_contract"),
  criterion("2.1.2", "A", "No Keyboard Trap", "state_contract"),
  criterion("2.1.4", "A", "Character Key Shortcuts"),
  criterion("2.2.1", "A", "Timing Adjustable"),
  criterion("2.2.2", "A", "Pause, Stop, Hide", "state_contract"),
  criterion("2.3.1", "A", "Three Flashes or Below Threshold"),
  criterion("2.4.1", "A", "Bypass Blocks"),
  criterion("2.4.2", "A", "Page Titled"),
  criterion("2.4.3", "A", "Focus Order", "state_contract"),
  criterion("2.4.4", "A", "Link Purpose (In Context)"),
  criterion("2.4.5", "AA", "Multiple Ways"),
  criterion("2.4.6", "AA", "Headings and Labels"),
  criterion("2.4.7", "AA", "Focus Visible", "state_contract"),
  criterion("2.4.11", "AA", "Focus Not Obscured (Minimum)", "state_contract"),
  criterion("2.5.1", "A", "Pointer Gestures"),
  criterion("2.5.2", "A", "Pointer Cancellation"),
  criterion("2.5.3", "A", "Label in Name"),
  criterion("2.5.4", "A", "Motion Actuation"),
  criterion("2.5.7", "AA", "Dragging Movements"),
  criterion("2.5.8", "AA", "Target Size (Minimum)"),
  criterion("3.1.1", "A", "Language of Page"),
  criterion("3.1.2", "AA", "Language of Parts"),
  criterion("3.2.1", "A", "On Focus"),
  criterion("3.2.2", "A", "On Input"),
  criterion("3.2.3", "AA", "Consistent Navigation"),
  criterion("3.2.4", "AA", "Consistent Identification"),
  criterion("3.2.6", "A", "Consistent Help"),
  criterion("3.3.1", "A", "Error Identification"),
  criterion("3.3.2", "A", "Labels or Instructions"),
  criterion("3.3.3", "AA", "Error Suggestion"),
  criterion("3.3.4", "AA", "Error Prevention (Legal, Financial, Data)"),
  criterion("3.3.7", "A", "Redundant Entry"),
  criterion("3.3.8", "AA", "Accessible Authentication (Minimum)"),
  criterion("4.1.2", "A", "Name, Role, Value"),
  criterion("4.1.3", "AA", "Status Messages"),
]);

export function buildCanonicalAccessibilityRouteInventory(routeContract) {
  if (
    !isRecord(routeContract) ||
    !Array.isArray(routeContract.canonical_navigation_targets) ||
    !isRecord(routeContract.counts) ||
    routeContract.counts.canonical_navigation_targets !==
      routeContract.canonical_navigation_targets.length
  ) {
    throw new Error("accessibility_canonical_route_contract_invalid");
  }
  const routes = routeContract.canonical_navigation_targets.map((target) =>
    Object.freeze({
      routeId: requiredText(target.route_key, "accessibility_route_id_invalid"),
      pathTemplate: canonicalPathTemplate(target),
      contexts: Object.freeze(requiredStringArray(target.contexts)),
    }),
  );
  const routeIds = routes.map(({ routeId }) => routeId);
  if (new Set(routeIds).size !== routeIds.length) {
    throw new Error("accessibility_canonical_route_contract_duplicate");
  }
  return Object.freeze({
    sourceRevision: requiredText(
      routeContract.source_revision,
      "accessibility_route_source_revision_invalid",
    ),
    routes: Object.freeze(routes),
  });
}

export function materializeAccessibilityRoutePath(route, scope) {
  const tenantId = requiredText(
    scope?.tenantId,
    "accessibility_tenant_scope_required",
  );
  const projectId = route.pathTemplate.includes(":projectId")
    ? requiredText(scope?.projectId, "accessibility_project_scope_required")
    : null;
  return route.pathTemplate
    .replace(":tenantId", encodeURIComponent(tenantId))
    .replace(
      ":projectId",
      projectId === null ? ":projectId" : encodeURIComponent(projectId),
    );
}

export function assertCompleteAccessibilityRouteResults(inventory, results) {
  const errors = validateAccessibilityRouteResults(inventory, results);
  if (errors.length > 0) throw new Error(errors.join("\n"));
}

export function validateAccessibilityRouteResults(inventory, results) {
  const errors = [];
  const expectedIds = new Set(
    (inventory?.routes ?? []).map(({ routeId }) => routeId),
  );
  const resultsById = new Map();
  for (const result of Array.isArray(results) ? results : []) {
    const routeId =
      typeof result?.routeId === "string" ? result.routeId : "invalid";
    if (resultsById.has(routeId)) {
      errors.push(`accessibility_route_duplicate:${routeId}`);
      continue;
    }
    resultsById.set(routeId, result);
  }
  for (const routeId of expectedIds) {
    const result = resultsById.get(routeId);
    if (!result) {
      errors.push(`accessibility_route_missing:${routeId}`);
      continue;
    }
    const states = Array.isArray(result.states) ? result.states : [];
    const statesById = new Map();
    for (const state of states) {
      const stateId =
        typeof state?.stateId === "string" ? state.stateId : "invalid";
      if (statesById.has(stateId)) {
        errors.push(`accessibility_state_duplicate:${routeId}:${stateId}`);
      } else {
        statesById.set(stateId, state);
      }
    }
    for (const stateId of REQUIRED_ACCESSIBILITY_STATES) {
      const state = statesById.get(stateId);
      if (!state) {
        errors.push(`accessibility_state_missing:${routeId}:${stateId}`);
      } else if (!EXECUTED_STATUSES.has(state.status)) {
        errors.push(
          `accessibility_state_not_executed:${routeId}:${stateId}:${state.status}`,
        );
      } else if (
        !Array.isArray(state.evidence) ||
        state.evidence.length === 0
      ) {
        errors.push(
          `accessibility_state_evidence_missing:${routeId}:${stateId}`,
        );
      }
    }
  }
  for (const routeId of resultsById.keys()) {
    if (!expectedIds.has(routeId))
      errors.push(`accessibility_route_unknown:${routeId}`);
  }
  return errors;
}

export function validateCriterionLedger(
  ledger,
  { allowTemplate = false } = {},
) {
  const errors = validateJsonSchema(LEDGER_SCHEMA, ledger);
  if (!isRecord(ledger)) return errors;
  if (!allowTemplate && ledger.record_kind !== "evidence") {
    errors.push("$.record_kind must be evidence for an executed ledger");
  }
  const criteria = Array.isArray(ledger.criteria) ? ledger.criteria : [];
  const expectedById = new Map(
    WCAG_22_AA_CRITERIA.map((item) => [item.id, item]),
  );
  const actualIds = criteria.map((item) => item?.criterion_id);
  if (new Set(actualIds).size !== actualIds.length) {
    errors.push("$.criteria must not contain duplicate criterion_id values");
  }
  for (const expected of WCAG_22_AA_CRITERIA) {
    const actual = criteria.find(
      ({ criterion_id: id } = {}) => id === expected.id,
    );
    if (!actual) {
      errors.push(`$.criteria is missing WCAG 2.2 criterion ${expected.id}`);
      continue;
    }
    if (actual.level !== expected.level || actual.title !== expected.title) {
      errors.push(
        `$.criteria criterion ${expected.id} metadata does not match the catalog`,
      );
    }
  }
  for (const id of actualIds) {
    if (!expectedById.has(id))
      errors.push(`$.criteria contains unknown criterion ${id}`);
  }

  const assessmentKeys = new Set();
  for (const [index, assessment] of (ledger.assessments ?? []).entries()) {
    if (!isRecord(assessment)) continue;
    const key = `${assessment.criterion_id}:${assessment.surface}`;
    if (assessmentKeys.has(key))
      errors.push(`$.assessments[${index}] duplicates ${key}`);
    assessmentKeys.add(key);
    const criterionEntry = criteria.find(
      ({ criterion_id: id } = {}) => id === assessment.criterion_id,
    );
    const expectedMethod = criterionEntry?.methods?.[assessment.surface];
    if (expectedMethod !== assessment.method) {
      errors.push(
        `$.assessments[${index}].method must match criterion method ${expectedMethod}`,
      );
    }
    if (assessment.method === "manual_at" && EXECUTED_STATUSES.has(assessment.status)) {
      const judgment = assessment.judgment;
      const judgmentIsBound =
        isRecord(judgment) &&
        judgment.output === (assessment.status === "passed" ? "accepted" : "rejected") &&
        judgment.revision === ledger.source_revision;
      if (!judgmentIsBound) {
        errors.push(
          `$.assessments[${index}] manual_at assessment requires a revision-bound structured judgment`,
        );
      }
    }
    if (
      !EXECUTED_STATUSES.has(assessment.status) &&
      assessment.judgment !== null &&
      assessment.judgment !== undefined
    ) {
      errors.push(
        `$.assessments[${index}] unexecuted assessment must not attach a judgment`,
      );
    }
    if (assessment.status === "passed" && assessment.evidence?.length === 0) {
      errors.push(
        `$.assessments[${index}] passed assessment requires evidence`,
      );
    }
    if (assessment.status === "failed" && assessment.evidence?.length === 0) {
      errors.push(
        `$.assessments[${index}] failed assessment requires evidence`,
      );
    }
    if (assessment.status === "blocked" && !assessment.blocker_reason) {
      errors.push(
        `$.assessments[${index}] blocked assessment requires blocker_reason`,
      );
    }
  }

  if (!allowTemplate) {
    for (const criterionEntry of criteria) {
      for (const surface of SURFACES) {
        if (!assessmentKeys.has(`${criterionEntry.criterion_id}:${surface}`)) {
          errors.push(
            `$.assessments is missing ${criterionEntry.criterion_id}:${surface}`,
          );
        }
      }
    }
  }
  return errors;
}

function criterion(id, level, title, automatedMethod = "hybrid") {
  return Object.freeze({
    id,
    level,
    title,
    methods: Object.freeze({
      web: automatedMethod,
      desktop_browser_qa: automatedMethod,
      browser_extension: automatedMethod,
      native_electron: "manual_at",
    }),
  });
}

function canonicalPathTemplate(target) {
  if (!isRecord(target)) throw new Error("accessibility_route_target_invalid");
  if (target.route_family === "agent-workspace")
    return "/tenant/:tenantId/agent-workspace";
  if (target.route_family === "tenant") {
    const relativePath = requiredRelativePath(target.relative_path);
    return `/tenant/:tenantId${relativePath ? `/${relativePath}` : ""}`;
  }
  const projectRoot = "/tenant/:tenantId/project/:projectId";
  if (target.route_family === "project-blackboard-dynamic")
    return `${projectRoot}/blackboard`;
  const contexts = requiredStringArray(target.contexts);
  if (contexts.includes("agent")) {
    const relativePath = requiredRelativePath(target.relative_path);
    return `${projectRoot}/agent${relativePath ? `/${relativePath}` : ""}`;
  }
  const relativePath = requiredRelativePath(target.relative_path);
  return `${projectRoot}${relativePath ? `/${relativePath}` : ""}`;
}

function requiredRelativePath(value) {
  if (typeof value !== "string" || value.includes("?") || value.includes("#")) {
    throw new Error("accessibility_route_relative_path_invalid");
  }
  return value.replace(/^\/+|\/+$/gu, "");
}

function requiredStringArray(value) {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || !item)
  ) {
    throw new Error("accessibility_route_contexts_invalid");
  }
  return value;
}

function requiredText(value, reasonCode) {
  if (typeof value !== "string" || !value || value.trim() !== value)
    throw new Error(reasonCode);
  return value;
}

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
