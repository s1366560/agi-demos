const SANDBOX_LOCAL_STORAGE_ERROR =
  "Failed to read the 'localStorage' property from 'Window': The document is sandboxed and lacks the 'allow-same-origin' flag.";
const SANDBOX_SCRIPT_BLOCK =
  /^Blocked script execution in 'blob:http:\/\/127\.0\.0\.1:\d+\/[0-9a-f-]+' because the document's frame is sandboxed and the 'allow-scripts' permission is not set\.$/u;

export function isExpectedBrowserQaSecurityDiagnostic(scenarioId, kind, message) {
  if (scenarioId !== 'artifact-preview') return false;
  if (kind === 'page') return message === SANDBOX_LOCAL_STORAGE_ERROR;
  return kind === 'console' && SANDBOX_SCRIPT_BLOCK.test(message);
}
