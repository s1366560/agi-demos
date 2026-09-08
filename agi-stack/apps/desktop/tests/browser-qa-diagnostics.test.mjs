import assert from "node:assert/strict";
import test from "node:test";
import { isExpectedBrowserQaSecurityDiagnostic } from "../browser-qa/diagnostics.mjs";

test("Browser QA ignores only the expected opaque sandbox enforcement diagnostics", () => {
  assert.equal(
    isExpectedBrowserQaSecurityDiagnostic(
      "artifact-preview",
      "page",
      "Failed to read the 'localStorage' property from 'Window': The document is sandboxed and lacks the 'allow-same-origin' flag.",
    ),
    true,
  );
  assert.equal(
    isExpectedBrowserQaSecurityDiagnostic(
      "artifact-preview",
      "console",
      "Blocked script execution in 'blob:http://127.0.0.1:5193/1985b031-4281-4ae8-a482-21799c988bac' because the document's frame is sandboxed and the 'allow-scripts' permission is not set.",
    ),
    true,
  );
  assert.equal(
    isExpectedBrowserQaSecurityDiagnostic(
      "workspace-collaboration",
      "console",
      "Blocked script execution in 'blob:http://127.0.0.1:5193/1985b031-4281-4ae8-a482-21799c988bac' because the document's frame is sandboxed and the 'allow-scripts' permission is not set.",
    ),
    false,
  );
  assert.equal(
    isExpectedBrowserQaSecurityDiagnostic(
      "artifact-preview",
      "console",
      "Application failed to render",
    ),
    false,
  );
});
