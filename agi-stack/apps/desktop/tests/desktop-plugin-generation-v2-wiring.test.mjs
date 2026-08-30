import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

function source(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');
}

test('desktop renderer owns a protocol-v2 generation host through the trusted sidecar IPC seam', () => {
  const hook = source('src/plugins/useDesktopPluginGenerationV2.ts');
  const host = source('src/plugins/DesktopRendererGenerationHostV2.tsx');
  const context = source('src/plugins/desktopRendererGenerationContextV2.tsx');
  const authenticatedShellBoundary = source('src/plugins/DesktopRendererAuthenticatedShellV2.tsx');
  const authenticationRouteBoundary = source(
    'src/plugins/DesktopRendererAuthenticationRouterV2.tsx'
  );
  const routeBoundary = source('src/plugins/DesktopRendererProductionRouterV2.tsx');
  const workbenchSurface = source('src/plugins/DesktopWorkbenchSurfaceV2.tsx');
  const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
  const routeHost = source('src/features/navigation/desktopHashRouteHost.ts');
  const lifecycle = source('../../packages/plugin-runtime/src/rendererLifecycle.ts');
  const app = source('src/App.tsx');
  const agentSocket = source('src/hooks/useAgentSocket.ts');
  const agentSocketLease = source('src/hooks/agentSocketGenerationLeaseV2.ts');
  const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
  const authority = source('src/plugins/desktopRendererAuthorityStateV2.ts');
  const main = source('src/main.tsx');

  assert.match(hook, /RendererPluginRuntimeV2\(\s*["']desktop-renderer["']/u);
  assert.match(hook, /createDesktopRendererDefinitionsV2/u);
  assert.match(hook, /validateDesktopRendererContributionsV2/u);
  assert.match(hook, /RendererGenerationLeaseStoreV2/u);
  assert.match(hook, /RendererGenerationStatusStoreV2/u);
  assert.match(hook, /projectRendererPluginGenerationStateV2/u);
  assert.match(hook, /useLayoutEffect/u);
  assert.match(hook, /desktopRendererLeaseStoreV2\.commit\(snapshot\)/u);
  assert.match(hook, /desktopRendererLeaseStoreV2\.acquireGeneration\(generation\)/u);
  assert.match(hook, /return state/u);
  assert.match(hook, /if \(!enabled\) \{\s*scheduleClose\(\);\s*return;\s*\}/u);
  assert.doesNotMatch(hook, /if \(!enabled\) return \(\) => scheduleClose\(\)/u);
  assert.match(hook, /DesktopRendererDistributionReconcilerV2/u);
  assert.match(hook, /platform_plugin_renderer_distribution_current_v2/u);
  assert.match(hook, /window\.__MEMSTACK_DESKTOP__\?\.core\?\.invoke/u);
  assert.doesNotMatch(
    hook,
    /desktopApiFetch|desktopApiCredential|desktopLaunchCapability|Authorization|X-Agistack-Launch/u
  );
  assert.doesNotMatch(hook, /memstack-default-bootstrap\.v2\.json|bootstrapProfileV2/u);
  assert.match(hook, /startRendererGenerationPollingV2/u);
  assert.match(hook, /source:\s*fetchDesktopPluginDistributionV2/u);
  assert.match(
    hook,
    /apply:\s*\(payload\) => desktopRendererDistributionReconcilerV2\.apply\(payload\)/u
  );
  assert.match(hook, /\}, \[enabled\]\);/u);
  const remoteFetchIndex = lifecycle.search(/await options\.source\(signal\)/u);
  const applyIndex = lifecycle.search(/await applyRendererDistributionV2\(options, payload\)/u);
  assert.ok(
    remoteFetchIndex >= 0 && applyIndex > remoteFetchIndex,
    'a stopped IPC request must be checked before its payload can be applied'
  );
  assert.match(host, /useDesktopPluginGenerationV2\(\s*config,\s*enabled\s*,?\s*\)/u);
  assert.match(host, /DesktopRendererCompositionPortV2/u);
  assert.doesNotMatch(host, /AppRouteRegistryRefs/u);
  assert.match(host, /resolveDesktopRendererAuthorityStateV2/u);
  assert.match(host, /projectDesktopRouteRegistryV2/u);
  assert.match(host, /projectDesktopNavigationRegistryV2/u);
  assert.match(context, /DesktopRendererGenerationContextV2/u);
  assert.match(context, /DesktopRendererAuthorityContextV2/u);
  assert.doesNotMatch(context, /@agistack\/plugin-runtime/u);
  assert.match(host, /const actions:[^=]+?=\s*Object\.freeze/su);
  assert.match(host, /acquireOperationLease/u);
  assert.match(context, /children/u);
  assert.match(routeBoundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(routeBoundary, /projectDesktopWorkbenchCompositionV2/u);
  assert.match(routeBoundary, /viewModel/u);
  assert.doesNotMatch(routeBoundary, /childrenAuthority|ReactNode|readonly children/u);
  assert.match(authenticationRouteBoundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(authenticationRouteBoundary, /readonly children:\s*ReactNode/u);
  assert.doesNotMatch(authenticationRouteBoundary, /projectDesktopWorkbenchCompositionV2/u);
  assert.match(authenticatedShellBoundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(authenticatedShellBoundary, /projectDesktopAuthenticatedShellCompositionV2/u);
  assert.match(authenticatedShellBoundary, /readonly children:\s*ReactNode/u);
  assert.doesNotMatch(authenticatedShellBoundary, /render[A-Z][A-Za-z]+\??:/u);
  assert.match(routeBoundary, /registry=\{state\.routeRegistry\}/u);
  assert.match(routeBoundary, /acquireOperationLease=\{actions\.acquireOperationLease\}/u);
  assert.match(
    routeBoundary,
    /Omit<[\s\S]+?'acquireOperationLease'\s*\|\s*'children'\s*\|\s*'registry'[\s\S]+?>/u
  );
  assert.match(routeHost, /acquireOperationLease/u);
  assert.match(routeHost, /finally\s*\{\s*await operationLease\?\.release\(\)/u);
  assert.match(app, /useDesktopRendererGenerationHostV2\(/u);
  assert.match(app, /createDesktopRendererAppCompositionPortV2/u);
  assert.match(app, /DesktopRendererGenerationProviderV2/u);
  assert.match(app, /DesktopRendererAuthenticatedShellV2/u);
  assert.match(app, /DesktopRendererAuthenticationRouterV2/u);
  assert.match(app, /DesktopRendererProductionRouterV2/u);
  assert.match(app, /desktopWorkbenchSurfaceViewModelV2/u);
  assert.doesNotMatch(
    app,
    /<(?:ChatPanel|WorkspaceOverview|WorkspaceCollaborationCanvas|MyWorkQueue|ActivityInbox|NewThreadComposer|SessionWorkspace)\b/u
  );
  assert.doesNotMatch(app, /<DesktopProductionRouter/u);
  assert.match(app, /desktopRendererGenerationV2\.meta\.digest/u);
  assert.match(app, /desktopRendererGenerationV2\.meta\.status/u);
  assert.match(app, /desktopRendererGenerationV2\.meta\.target/u);
  assert.match(
    app,
    new RegExp(
      String.raw`useAgentSocket\([\s\S]+?` +
        String.raw`desktopRendererGenerationV2\.actions\.acquireOperationLease[\s\S]+?\)`,
      'u'
    )
  );
  assert.match(agentSocket, /AgentSocketGenerationLeaseFactoryV2/u);
  assert.match(agentSocket, /acquireAgentSocketGenerationLeaseV2\(acquireGenerationLease\)/u);
  assert.match(agentSocket, /generationLease\.constructSocket\(\(\) =>/u);
  const socketLeaseIndex = agentSocket.indexOf(
    'acquireAgentSocketGenerationLeaseV2(acquireGenerationLease)'
  );
  const socketConnectIndex = agentSocket.indexOf('const connect = () =>', socketLeaseIndex);
  assert.ok(socketLeaseIndex >= 0 && socketConnectIndex > socketLeaseIndex);
  assert.match(
    agentSocket,
    /\[\s*acquireGenerationLease,[\s\S]+?socketAuthenticationAvailable,[\s\S]+?\]\);/u
  );
  const socketCleanupSequence = [
    String.raw`socket\.onopen = null;`,
    String.raw`socket\.onerror = null;`,
    String.raw`socket\.onmessage = null;`,
    String.raw`socket\.onclose = null;`,
    String.raw`socket\.close\(\);`,
    String.raw`generationLease\.release\(\)`,
  ].join(String.raw`[\s\S]+?`);
  assert.match(agentSocket, new RegExp(socketCleanupSequence, 'u'));
  assert.match(agentSocketLease, /lease\.kind !== 'generation'/u);
  assert.match(agentSocketLease, /lease\.digest\?\.trim\(\)/u);
  assert.match(agentSocketLease, /releasePromise/u);
  assert.doesNotMatch(app, /useDesktopPluginGenerationV2/u);
  assert.doesNotMatch(app, /resolveDesktopRendererAuthorityStateV2/u);
  assert.doesNotMatch(app, /projectDesktopRouteRegistryV2/u);
  assert.doesNotMatch(app, /projectDesktopNavigationRegistryV2/u);
  assert.doesNotMatch(app, /DesktopRendererAuthorityContextV2/u);
  assert.doesNotMatch(app, /createAppRouteRegistry/u);
  assert.doesNotMatch(app, /AppRouteRegistryRefs/u);
  assert.doesNotMatch(app, /CANONICAL_DESKTOP_ROUTE_IDS\.map/u);
  assert.doesNotMatch(artifactCatalog, /createRegistry|AppRouteRegistryRefs/u);
  assert.doesNotMatch(artifactCatalog, /createAppTenantCreationRouteRegistry/u);
  assert.doesNotMatch(artifactCatalog, /DESKTOP_DEFAULT_(?:ROUTE|NAVIGATION)_ARTIFACT_ID_V2/u);
  assert.doesNotMatch(artifactCatalog, /desktop\.(?:routes\.production|navigation\.default)\.v1/u);
  assert.match(authority, /composition\.createRouteRegistry\(artifact\.id\)/u);
  assert.doesNotMatch(authority, /AppRouteRegistryRefs/u);
  assert.match(composition, /createAppAuthenticationRouteRegistry/u);
  assert.match(composition, /createAppTenantCreationRouteRegistry/u);
  assert.match(composition, /DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2/u);
  assert.match(composition, /resolveAuthenticatedShellSurface/u);
  assert.match(composition, /DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2/u);
  assert.match(composition, /DesktopWorkbenchSurfaceV2/u);
  assert.doesNotMatch(composition, /const DesktopWorkbenchSurfaceV2\b/u);
  assert.match(workbenchSurface, /type DesktopWorkbenchViewV2\s*=/u);
  assert.match(workbenchSurface, /<SessionWorkspace/u);
  assert.match(main, /activateDesktopPluginGenerationRootV2\(\)/u);
  assert.match(main, /root\.unmount\(\)/u);
  assert.match(main, /deactivateDesktopPluginGenerationRootV2\(\)/u);
});

test('desktop authenticated shell is an explicit ordered production contribution', () => {
  const profile = readFileSync(
    new URL(
      '../../../../config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
      import.meta.url
    ),
    'utf8'
  );
  const bootstrap = JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8'
    )
  );
  const shellEntryId = 'builtin-desktop-authenticated-shell-surface';
  const workbenchEntryId = 'builtin-desktop-workbench-surface';
  const shellProfileIndex = profile.indexOf(`entry_id: ${shellEntryId}`);
  const workbenchProfileIndex = profile.indexOf(`entry_id: ${workbenchEntryId}`);
  const shellProfile = profile.slice(shellProfileIndex, workbenchProfileIndex);
  const workbenchProfile = profile.slice(
    workbenchProfileIndex,
    profile.indexOf('\n    - entry_id:', workbenchProfileIndex + 1)
  );

  assert.ok(shellProfileIndex >= 0);
  assert.ok(workbenchProfileIndex > shellProfileIndex);
  assert.match(shellProfile, /id:\s*desktop\.authenticated-shell-surface/u);
  assert.match(shellProfile, /order:\s*80/u);
  assert.match(shellProfile, /desktop\.ui-slots\.authenticated-shell-surface\.v1/u);
  assert.match(workbenchProfile, /id:\s*desktop\.workbench-surface/u);
  assert.match(workbenchProfile, /order:\s*90/u);
  assert.match(workbenchProfile, /desktop\.ui-slots\.workbench-surface\.v2/u);

  const shellBootstrapIndex = bootstrap.entries.findIndex(
    ({ entry_id: entryId }) => entryId === shellEntryId
  );
  const workbenchBootstrapIndex = bootstrap.entries.findIndex(
    ({ entry_id: entryId }) => entryId === workbenchEntryId
  );
  const shellBootstrap = bootstrap.entries[shellBootstrapIndex];
  const workbenchBootstrap = bootstrap.entries[workbenchBootstrapIndex];

  assert.ok(shellBootstrapIndex >= 0);
  assert.ok(workbenchBootstrapIndex > shellBootstrapIndex);
  assert.equal(shellBootstrap.config.id, 'desktop.authenticated-shell-surface');
  assert.equal(shellBootstrap.config.order, 80);
  assert.deepEqual(shellBootstrap.config.payload.artifact_refs, [
    'desktop.ui-slots.authenticated-shell-surface.v1',
  ]);
  assert.equal(workbenchBootstrap.config.id, 'desktop.workbench-surface');
  assert.equal(workbenchBootstrap.config.order, 90);
  assert.deepEqual(workbenchBootstrap.config.payload.artifact_refs, [
    'desktop.ui-slots.workbench-surface.v2',
  ]);
});

test('desktop UI slot consumers use the pinned V2 authority without V1 fallback', () => {
  const hook = source('src/features/settings/usePlatformPluginUiSlots.ts');
  const conversationSlots = source('src/features/chat/PlatformPluginConversationSlots.tsx');
  const settingsSlots = source('src/features/settings/PlatformPluginUiSlots.tsx');
  const client = source('src/api/client.ts');
  const activity = source('src/features/settings/usePluginManagement.ts');

  assert.match(hook, /useDesktopRendererAuthorityV2/u);
  assert.doesNotMatch(hook, /DesktopApiClient|getPlatformPluginSnapshot/u);
  assert.doesNotMatch(hook, /builtinUiFallbackSnapshot|BUILTIN_UI_SLOT_DEFINITIONS/u);
  assert.doesNotMatch(conversationSlots, /usePlatformPluginUiSlots\(\{ active, config \}\)/u);
  assert.match(conversationSlots, /data-module-ref/u);
  assert.doesNotMatch(conversationSlots, /SignedUiModuleBoundary|signed:/u);
  assert.doesNotMatch(settingsSlots, /SignedUiModuleBoundary|signed:/u);
  assert.doesNotMatch(
    client,
    /getPlatformPlugin(?:ApplyState|Snapshot|FrontendModule)|platform-plugins\/(?:apply-state|snapshot|frontend)/u
  );
  assert.doesNotMatch(activity, /snapshotState|getPlatformPluginApplyState/u);
});

test('every desktop build path resolves the shared protocol-v2 runtime package', () => {
  const tsconfig = source('tsconfig.json');
  const vite = source('vite.config.ts');
  const electronVite = source('electron.vite.config.ts');

  for (const content of [tsconfig, vite, electronVite]) {
    assert.match(content, /@agistack\/plugin-runtime/u);
  }
});
