import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, "utf8") : "";
}

const app = source("src/App.tsx");
const retiredProvider = source(
  "src/features/workspace/desktopConversationLifecycleClientProviderV2.ts",
);
const authorityModule = source(
  "src/plugins/desktopConversationLifecycleAuthorityModuleV2.ts",
);
const generationHook = desktopProductionRuntimeSource();

test("App creates one generation-backed conversation lifecycle operation port", () => {
  assert.match(app, /createDesktopConversationLifecycleOperationsV2/u);
  assert.match(
    app,
    /const desktopConversationLifecycleOperationsV2 = useMemo\([\s\S]*?createDesktopConversationLifecycleOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(
    app,
    /createDesktopConversationLifecycleClientProviderV2/u,
  );
  assert.doesNotMatch(app, /desktopConversationLifecycleClientProviderV2/u);
  assert.doesNotMatch(app, /desktopConversationLifecycleClientV2/u);
  assert.equal(retiredProvider, "");
});

test("rename uses the exact session generation authority without changing UI reconciliation", () => {
  const handler = functionSource(app, "renameConversation");

  assert.match(handler, /const requestConfig = configRef\.current/u);
  assert.match(handler, /expectedScopeEpoch = configScopeEpochRef\.current/u);
  assert.match(
    handler,
    /expectedContextRevision = contextRevisionRef\.current/u,
  );
  assert.match(handler, /Invalid conversation lifecycle scope/u);
  assert.match(
    handler,
    /desktopConversationLifecycleOperationsV2\.updateAgentConversationTitle\(\{[\s\S]*?config: requestConfig,[\s\S]*?conversation,[\s\S]*?title,[\s\S]*?\}\)/u,
  );
  assert.match(handler, /replaceConversationInWorkspaceRows/u);
  assert.match(handler, /toast\.conversationRenameSuccess/u);
  assert.match(handler, /setAgentConversationSession/u);
  assert.doesNotMatch(
    handler,
    /desktopConversationLifecycleClientV2|new DesktopApiClient/u,
  );
});

test("summary keeps its cloud and stale-result guards around one session lease", () => {
  const handler = functionSource(app, "regenerateConversationSummary");

  assert.match(handler, /requestConfig\.mode !== 'cloud'/u);
  assert.match(handler, /Invalid conversation summary scope/u);
  assert.match(handler, /conversationSummaryMutationRequestRef\.current/u);
  assert.match(
    handler,
    /desktopConversationLifecycleOperationsV2\.generateAgentConversationSummary\(\{[\s\S]*?config: requestConfig,[\s\S]*?conversation: currentSession\.conversation,[\s\S]*?\}\)/u,
  );
  assert.match(handler, /replaceConversationInWorkspaceRows/u);
  assert.match(handler, /setAgentConversationSession/u);
  assert.doesNotMatch(
    handler,
    /desktopConversationLifecycleClientV2|new DesktopApiClient/u,
  );
});

test("delete uses one session lease and preserves selected-session cleanup", () => {
  const handler = functionSource(app, "deleteConversation");

  assert.match(handler, /const requestConfig = configRef\.current/u);
  assert.match(handler, /Invalid conversation lifecycle scope/u);
  assert.match(
    handler,
    /desktopConversationLifecycleOperationsV2\.deleteAgentConversation\(\{[\s\S]*?config: requestConfig,[\s\S]*?conversation,[\s\S]*?\}\)/u,
  );
  assert.match(handler, /removeConversationFromWorkspaceRows/u);
  assert.match(handler, /toast\.conversationDeleteSuccess/u);
  assert.match(handler, /agentConversationSessionRef\.current = null/u);
  assert.match(handler, /selectWorkspace\(normalizedWorkspaceId, projectId\)/u);
  assert.doesNotMatch(
    handler,
    /desktopConversationLifecycleClientV2|new DesktopApiClient/u,
  );
});

test("conversation lifecycle authority registers one exact three-method generation service", () => {
  assert.match(
    generationHook,
    /desktopConversationLifecycleAuthorityDefinitionV2/u,
  );
  assert.match(
    authorityModule,
    /service:desktop-renderer\.conversation-lifecycle-authority/u,
  );
  for (const method of [
    "deleteAgentConversation",
    "generateAgentConversationSummary",
    "updateAgentConversationTitle",
  ]) {
    assert.match(authorityModule, new RegExp(method, "u"));
  }
  assert.match(authorityModule, /acquireServiceOperationLease/u);
  assert.doesNotMatch(
    authorityModule,
    /DesktopConversationLifecycleClientProvider/u,
  );
});

function functionSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = async`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf("\n  };", start);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end + 5);
}
