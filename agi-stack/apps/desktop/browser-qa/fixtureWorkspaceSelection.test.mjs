import assert from "node:assert/strict";
import test from "node:test";

import { fixtureWorkspaceSwitch } from "./fixtureWorkspaceSelection.mjs";

const restoredProject = "c07b6654-759c-4c8f-abcd-911e6bc492e2";
const fixtureProject = "daed6626-6b4e-4ccf-8fb8-700ae17f3302";

test("a restored workspace from another project is switched to the fixture", () => {
  const body = fixtureWorkspaceSwitch(
    { tenant_id: "tenant-a", project_id: restoredProject, revision: 7 },
    "tenant-a",
    fixtureProject,
  );
  assert.equal(body.project_id, fixtureProject);
  assert.notEqual(body.project_id, restoredProject);
  assert.equal(body.tenant_id, "tenant-a");
  assert.equal(body.expected_revision, 7);
});

test("the same fixture workspace is not switched again", () => {
  assert.equal(
    fixtureWorkspaceSwitch(
      { tenant_id: "tenant-a", project_id: fixtureProject, revision: 8 },
      "tenant-a",
      fixtureProject,
    ),
    null,
  );
});

test("the same project in another tenant is not reused", () => {
  const body = fixtureWorkspaceSwitch(
    { tenant_id: "tenant-b", project_id: fixtureProject, revision: 3 },
    "tenant-a",
    fixtureProject,
  );
  assert.equal(body.tenant_id, "tenant-a");
  assert.equal(body.project_id, fixtureProject);
  assert.equal(body.expected_revision, 3);
});
