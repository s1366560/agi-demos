import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  buildRunCompletionSummary,
  runCompletionOutcome,
} = require("/tmp/agistack-desktop-test-dist/src/features/session/runCompletionSummaryModel.js");
const {
  myWorkCompletionPresentation,
} = require("/tmp/agistack-desktop-test-dist/src/features/my-work/myWorkModel.js");

const readySnapshot = {
  id: "snapshot-1",
  run_id: "run-1",
  conversation_id: "conversation-1",
  run_revision: 3,
  environment_id: "environment-1",
  status: "ready",
  additions: 12,
  deletions: 4,
  files_changed: 2,
  truncated: false,
  captured_at: "2026-01-01T00:00:00Z",
  files: [],
};

function artifactVersion(overrides = {}) {
  return {
    id: "version-1",
    artifact_id: "artifact-1",
    source_artifact_id: "source-1",
    conversation_id: "conversation-1",
    run_id: "run-1",
    version: 1,
    status: "ready",
    revision: 1,
    filename: "report.md",
    mime_type: "text/markdown",
    path: "/tmp/report.md",
    relative_path: "report.md",
    bytes: 128,
    sources: [],
    checks: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

test("runCompletionOutcome only accepts terminal run statuses", () => {
  assert.equal(runCompletionOutcome("completed"), "completed");
  assert.equal(runCompletionOutcome(" Failed "), "failed");
  assert.equal(runCompletionOutcome("cancelled"), "cancelled");
  for (const status of [
    "running",
    "queued",
    "paused",
    "needs_input",
    "needs_approval",
    "ready_review",
    "disconnected",
    "interrupted",
    null,
    undefined,
    "",
  ]) {
    assert.equal(runCompletionOutcome(status), null, `status ${status}`);
  }
});

test("non-terminal runs never produce a summary card", () => {
  for (const status of ["running", "ready_review", "needs_input", null]) {
    assert.equal(
      buildRunCompletionSummary({ status, capabilityMode: "code" }),
      null,
      `status ${status}`,
    );
  }
});

test("terminal run with no evidence renders outcome only and omits empty sections", () => {
  const summary = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
  });
  assert.deepEqual(summary, {
    outcome: "completed",
    outcomeLabelKey: "session.statusCompleted",
    failureReason: null,
    completionSummary: null,
    durationMs: null,
    usage: null,
    tokenUsage: null,
    authorityState: null,
    authorityReasonCode: null,
    changes: null,
    artifacts: null,
    verification: null,
  });
});

test("recorded RunSummary fields replace renderer-derived completion metrics", () => {
  const summary = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    authoritySummary: {
      run_id: "run-1",
      tenant_id: "tenant-1",
      project_id: "project-1",
      conversation_id: "conversation-1",
      status: "completed",
      revision: 7,
      summary_state: "recorded",
      reason_code: null,
      started_at: "2026-08-04T01:00:00Z",
      completed_at: "2026-08-04T01:01:00Z",
      duration_ms: 60_000,
      input_tokens: 120,
      output_tokens: 80,
      cost_usd: 0.02,
      model_breakdown: [
        { model: "test-model", input_tokens: 120, output_tokens: 80 },
      ],
      completion_summary: "Implemented the requested change.",
      artifact_count: 2,
      checks_passed: 4,
      checks_failed: 1,
      files_changed: 3,
      lines_added: 20,
      lines_deleted: 5,
      evidence_references: [{ kind: "test", id: "focused" }],
    },
  });

  assert.equal(summary.completionSummary, "Implemented the requested change.");
  assert.equal(summary.durationMs, 60_000);
  assert.deepEqual(summary.tokenUsage, {
    inputTokens: 120,
    outputTokens: 80,
    costUsd: 0.02,
    modelBreakdown: [
      { model: "test-model", input_tokens: 120, output_tokens: 80 },
    ],
  });
  assert.deepEqual(summary.changes, {
    filesChanged: 3,
    additions: 20,
    deletions: 5,
    truncated: false,
    link: { tab: "changes", labelKey: "session.canvasChanges" },
  });
  assert.equal(summary.artifacts.totalCount, 2);
  assert.deepEqual(summary.verification, {
    total: 5,
    passedCount: 4,
    failedCount: 1,
    pendingCount: 0,
    link: { tab: "checks", labelKey: "session.canvasChecks" },
  });
  assert.equal(summary.authorityState, "recorded");
});

test("failed and cancelled runs surface the failure reason truthfully", () => {
  const failed = buildRunCompletionSummary({
    status: "failed",
    capabilityMode: "work",
    error: "  sandbox exited 1  ",
  });
  assert.equal(failed.outcome, "failed");
  assert.equal(failed.outcomeLabelKey, "session.statusFailed");
  assert.equal(failed.failureReason, "sandbox exited 1");

  const cancelled = buildRunCompletionSummary({
    status: "cancelled",
    capabilityMode: "work",
  });
  assert.equal(cancelled.outcome, "cancelled");
  assert.equal(cancelled.outcomeLabelKey, "session.statusCancelled");
  assert.equal(cancelled.failureReason, null);

  const completedWithStaleError = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "work",
    error: "stale error from an earlier attempt",
  });
  assert.equal(completedWithStaleError.failureReason, null);
});

test("changes section requires a ready snapshot with files and links to the Changes canvas", () => {
  const summary = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    changeSnapshot: readySnapshot,
  });
  assert.deepEqual(summary.changes, {
    filesChanged: 2,
    additions: 12,
    deletions: 4,
    truncated: false,
    link: { tab: "changes", labelKey: "session.canvasChanges" },
  });

  for (const snapshot of [
    null,
    { ...readySnapshot, status: "unavailable" },
    { ...readySnapshot, files_changed: 0 },
  ]) {
    const result = buildRunCompletionSummary({
      status: "completed",
      capabilityMode: "code",
      changeSnapshot: snapshot,
    });
    assert.equal(result.changes, null);
  }

  // Work mode exposes the same authoritative Changes canvas as code mode.
  const workMode = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "work",
    changeSnapshot: readySnapshot,
  });
  assert.equal(workMode.changes.filesChanged, 2);
  assert.deepEqual(workMode.changes.link, {
    tab: "changes",
    labelKey: "session.canvasChanges",
  });
});

test("artifacts section lists current versions only and links to the Artifacts canvas", () => {
  const stale = artifactVersion({ id: "version-old", version: 1, revision: 1 });
  const current = artifactVersion({
    id: "version-new",
    version: 2,
    revision: 1,
    updated_at: "2026-01-02T00:00:00Z",
  });
  const other = artifactVersion({
    id: "version-2",
    artifact_id: "artifact-2",
    filename: "notes.txt",
    mime_type: "text/plain",
  });
  const summary = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "work",
    artifactVersions: [stale, current, other],
  });
  assert.equal(summary.artifacts.totalCount, 2);
  assert.deepEqual(
    summary.artifacts.entries.map((entry) => entry.versionId).sort(),
    ["version-2", "version-new"],
  );
  assert.deepEqual(summary.artifacts.link, {
    tab: "artifacts",
    labelKey: "session.canvasArtifacts",
  });
  assert.equal(summary.artifacts.entries[0].title, "report.md");

  // Code mode exposes no Artifacts canvas tab, so no link is fabricated.
  const codeMode = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    artifactVersions: [current],
  });
  assert.equal(codeMode.artifacts.totalCount, 1);
  assert.equal(codeMode.artifacts.link, null);
});

test("verification claims always carry a navigable evidence link", () => {
  const versions = [
    artifactVersion({
      checks: [
        { id: "check-1", kind: "test", status: "passed" },
        { id: "check-2", kind: "lint", status: "failed" },
        { id: "check-3", kind: "build" },
      ],
    }),
  ];
  const codeMode = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    artifactVersions: versions,
  });
  assert.deepEqual(codeMode.verification, {
    total: 3,
    passedCount: 1,
    failedCount: 1,
    pendingCount: 1,
    link: { tab: "checks", labelKey: "session.canvasChecks" },
  });

  const workMode = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "work",
    artifactVersions: versions,
  });
  assert.deepEqual(workMode.verification.link, {
    tab: "verification",
    labelKey: "session.canvasVerification",
  });

  // No checks/verification canvas exists in unavailable mode: the claim is
  // omitted entirely rather than declared without inspectable evidence.
  const noCanvas = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "unavailable",
    artifactVersions: versions,
  });
  assert.equal(noCanvas.verification, null);

  // No declared checks: no verification claim at all.
  const noChecks = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    artifactVersions: [artifactVersion()],
  });
  assert.equal(noChecks.verification, null);
});

test("myWorkCompletionPresentation only appears for the ready-review group", () => {
  assert.equal(
    myWorkCompletionPresentation({
      group: "running",
      status: "running",
      error: null,
    }),
    null,
  );
  assert.equal(
    myWorkCompletionPresentation({
      group: "needs_input",
      status: "needs_input",
      error: null,
    }),
    null,
  );

  assert.deepEqual(
    myWorkCompletionPresentation({
      group: "ready_review",
      status: "ready_review",
      error: null,
    }),
    {
      outcomeLabelKey: "myWork.status.ready_review",
      tone: "success",
      detail: null,
    },
  );
  assert.deepEqual(
    myWorkCompletionPresentation({
      group: "ready_review",
      status: "completed",
      error: null,
    }),
    {
      outcomeLabelKey: "myWork.status.completed",
      tone: "success",
      detail: null,
    },
  );
  assert.deepEqual(
    myWorkCompletionPresentation({
      group: "ready_review",
      status: "failed",
      error: "  tests red  ",
    }),
    {
      outcomeLabelKey: "myWork.status.failed",
      tone: "danger",
      detail: "tests red",
    },
  );
  assert.deepEqual(
    myWorkCompletionPresentation({
      group: "ready_review",
      status: "cancelled",
      error: null,
    }),
    {
      outcomeLabelKey: "myWork.status.cancelled",
      tone: "warning",
      detail: null,
    },
  );
  // A completed run stale-grouped as running still lands in ready review.
  assert.deepEqual(
    myWorkCompletionPresentation({
      group: "running",
      status: "completed",
      error: null,
    }),
    {
      outcomeLabelKey: "myWork.status.completed",
      tone: "success",
      detail: null,
    },
  );
});

test("duration derives from authoritative run timestamps and stays null when absent", () => {
  const summary = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    runStartedAt: "2026-01-01T00:00:00Z",
    runCompletedAt: "2026-01-01T00:03:12Z",
  });
  assert.equal(summary.durationMs, 192_000);

  const missingCompleted = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    runStartedAt: "2026-01-01T00:00:00Z",
  });
  assert.equal(missingCompleted.durationMs, null);

  const reversed = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    runStartedAt: "2026-01-01T00:03:12Z",
    runCompletedAt: "2026-01-01T00:00:00Z",
  });
  assert.equal(reversed.durationMs, null);

  const unparseable = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
    runStartedAt: "not-a-date",
    runCompletedAt: "2026-01-01T00:00:00Z",
  });
  assert.equal(unparseable.durationMs, null);
});

test("usage passes through verbatim and defaults to null", () => {
  const usage = {
    currentTokens: 12_300,
    tokenBudget: 200_000,
    occupancyPct: 6.2,
  };
  const summary = buildRunCompletionSummary({
    status: "failed",
    capabilityMode: "code",
    usage,
  });
  assert.deepEqual(summary.usage, usage);

  const without = buildRunCompletionSummary({
    status: "completed",
    capabilityMode: "code",
  });
  assert.equal(without.usage, null);
});
