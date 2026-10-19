import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
const require = createRequire(import.meta.url);
const {
  projectToolResultPresentationV2: project,
} = require("/tmp/agistack-desktop-test-dist/src/features/chat/toolResultPresentationV2.js");
test("trusted tool projection keeps only declared presentation fields", () => {
  assert.deepEqual(
    project(
      {
        kind: "text",
        text: "<script>shown as text</script>",
        apiKey: "private",
      },
      "",
    ),
    { kind: "text", text: "<script>shown as text</script>" },
  );
  assert.deepEqual(
    project(
      {
        kind: "table",
        columns: ["name"],
        rows: [["value"]],
        credentials: "private",
      },
      "",
    ),
    { kind: "table", columns: ["name"], rows: [["value"]] },
  );
  assert.deepEqual(
    project({ kind: "diff", before: "a", after: "b", debug: "private" }, ""),
    { kind: "diff", before: "a", after: "b" },
  );
  assert.deepEqual(
    project(
      { tool_input: "private", credentials: "private" },
      "visible output",
    ),
    { kind: "text", text: "visible output" },
  );
  assert.deepEqual(
    project(
      { kind: "table", columns: ["name"], rows: [[{ token: "private" }]] },
      "",
      "summary",
    ),
    { kind: "summary", summary: "summary" },
  );
  assert.equal(
    project({ kind: "text", text: "a".repeat(100000) }, "").text.length,
    32768,
  );
});
test("computer presentation strips media URLs and raw result fields before sandbox rendering", () => {
  const {
    computerUseResultPresentationV2,
    computerUsePreviewBlobV2,
  } = require("/tmp/agistack-desktop-test-dist/src/features/chat/computerUseResultPresentationV2.js");
  const projected = computerUseResultPresentationV2(
    JSON.stringify({
      app: "Fixture",
      text: "[1] Visible control",
      icon: "data:image/png;base64,private",
      screenshot: {
        artifact_id: "cua-image-abcd",
        url: "file:///private/native.png",
        data_url: "private",
      },
      secret: "must not cross",
    }),
    "One control",
  );
  assert.deepEqual(project(projected, ""), {
    kind: "computer_use",
    app: "Fixture",
    text: "[1] Visible control",
    summary: "One control",
    screenshotArtifactId: "cua-image-abcd",
  });
  const blob = computerUsePreviewBlobV2("data:image/png;base64,AQID");
  assert.equal(blob.type, "image/png");
  assert.equal(blob.size, 3);
  assert.throws(() =>
    computerUsePreviewBlobV2("https://untrusted.test/image.png"),
  );
});

test("timeline and output inspector share the declared computer-use projection", () => {
  const {
    projectToolOutputPresentationV2,
  } = require("/tmp/agistack-desktop-test-dist/src/features/chat/toolResultOutputPresentationV2.js");
  assert.deepEqual(
    projectToolOutputPresentationV2({
      kind: "computer_use",
      output: {
        app: "Fixture",
        text: "Visible AX",
        screenshot: { artifact_id: "cua-image-abcd", url: "private" },
        secret: "private",
      },
      details: { kind: "text", text: "raw detail" },
      summary: "Observed",
    }),
    {
      kind: "computer_use",
      app: "Fixture",
      text: "Visible AX",
      summary: "Observed",
      screenshotArtifactId: "cua-image-abcd",
    },
  );
  assert.deepEqual(
    projectToolOutputPresentationV2({
      kind: "read",
      output: "Fallback",
      details: { kind: "text", text: "Declared" },
    }),
    { kind: "text", text: "Declared" },
  );
});
