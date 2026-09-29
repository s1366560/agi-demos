import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const workbenchSurfaceSource = readFileSync(
  new URL('../src/plugins/DesktopWorkbenchSurfaceV2.tsx', import.meta.url),
  'utf8',
);
const authenticatedShellSurfaceSource = readFileSync(
  new URL('../src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx', import.meta.url),
  'utf8',
);
const mainProcessSource = readFileSync(
  new URL('../electron/main/index.ts', import.meta.url),
  'utf8',
);
const preloadSource = readFileSync(
  new URL('../electron/preload/index.ts', import.meta.url),
  'utf8',
);
const bridgeTypes = readFileSync(
  new URL('../src/vite-env.d.ts', import.meta.url),
  'utf8',
);
const chromeStyles = readFileSync(
  new URL('../src/styles/chrome.css', import.meta.url),
  'utf8',
);
const titlebarSource = readFileSync(
  new URL('../src/features/chrome/DesktopTitlebar.tsx', import.meta.url),
  'utf8',
);
const titlebarStyles = readFileSync(
  new URL('../src/features/chrome/DesktopTitlebar.css', import.meta.url),
  'utf8',
);
const windowControlsSource = readFileSync(
  new URL('../src/features/chrome/WindowControls.tsx', import.meta.url),
  'utf8',
);
const statusBarSource = readFileSync(
  new URL('../src/features/chrome/DesktopStatusBar.tsx', import.meta.url),
  'utf8',
);
const statusBarStyles = readFileSync(
  new URL('../src/features/chrome/DesktopStatusBar.css', import.meta.url),
  'utf8',
);
const sidebarSource = readFileSync(
  new URL('../src/features/navigation/DesktopSidebar.tsx', import.meta.url),
  'utf8',
);
const tabBarSource = readFileSync(
  new URL('../src/features/chrome/WorkbenchTabBar.tsx', import.meta.url),
  'utf8',
);
const tabBarStyles = readFileSync(
  new URL('../src/features/chrome/WorkbenchTabBar.css', import.meta.url),
  'utf8',
);
const tabBarModelSource = readFileSync(
  new URL('../src/features/chrome/workbenchTabBarModel.ts', import.meta.url),
  'utf8',
);
const rightSidebarSource = readFileSync(
  new URL('../src/features/chrome/DesktopRightSidebar.tsx', import.meta.url),
  'utf8',
);
const rightSidebarSurfaceSource = readFileSync(
  new URL('../src/plugins/DesktopRightSidebarSurfaceV2.tsx', import.meta.url),
  'utf8',
);
const rightSidebarStyles = readFileSync(
  new URL('../src/features/chrome/DesktopRightSidebar.css', import.meta.url),
  'utf8',
);
const sessionWorkspaceSource = readFileSync(
  new URL('../src/features/session/SessionWorkspace.tsx', import.meta.url),
  'utf8',
);
const sidebarStyles = readFileSync(
  new URL('../src/features/navigation/DesktopSidebar.css', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

test('app shell mounts the desktop titlebar and status bar exactly once', () => {
  assert.equal(
    (authenticatedShellSurfaceSource.match(/<DesktopRendererTitlebarV2\b/g) ?? []).length,
    1,
  );
  assert.equal(
    (authenticatedShellSurfaceSource.match(/<DesktopRendererStatusBarV2\b/g) ?? []).length,
    1,
  );
  assert.doesNotMatch(authenticatedShellSurfaceSource, /<DesktopTitlebar\b/u);
  assert.doesNotMatch(authenticatedShellSurfaceSource, /<DesktopStatusBar\b/u);
  // The titlebar only renders inside the native desktop window shell.
  assert.match(appSource, /titlebar:\s*runsInNativeDesktop\s*\?[\s\S]*kind:\s*'visible'/u);
  assert.match(
    authenticatedShellSurfaceSource,
    /<DesktopRendererTitlebarV2 input=\{surfaces\.titlebar\}\s*\/>/u,
  );
  // Tabs and visibility belong to the session-scoped, in-memory work-panel state.
  assert.match(appSource, /useWorkPanels\(\)/);
  assert.doesNotMatch(appSource, /localStorage\.getItem\('agistack\.desktop\.rightSidebarOpen'\)/);
  assert.match(appSource, /rightSidebarOpen,/);
  assert.match(appSource, /onToggleRightSidebar:\s*toggleRightSidebar/);
  // The titlebar reuses the existing sidebar collapse state.
  assert.match(appSource, /sidebarCollapsed,/);
  assert.match(appSource, /onToggleSidebar:\s*\(\) =>/);
});

test('main window is frameless with platform-specific titlebar styles', () => {
  // macOS uses 'hidden' (not 'hiddenInset'): the inset variant keeps an
  // invisible native titlebar strip whose AppKit drag/zoom handling fights
  // the renderer's -webkit-app-region drag strip (window shakes while
  // dragging, double-click maximize lands wrong).
  assert.doesNotMatch(mainProcessSource, /titleBarStyle:\s*'hiddenInset'/);
  assert.match(mainProcessSource, /trafficLightPosition:\s*\{\s*x:\s*12,\s*y:\s*10\s*\}/);
  assert.match(mainProcessSource, /titleBarStyle:\s*'hidden'/);
  assert.match(mainProcessSource, /frame:\s*false/);
});

test('window controls reach the main window through the allowed command list', () => {
  assert.match(preloadSource, /'window_controls'/);
  assert.match(preloadSource, /windowControls/);
  assert.match(preloadSource, /platform:\s*process\.platform/);
  assert.match(mainProcessSource, /case 'window_controls'/);
  assert.match(mainProcessSource, /mainWindow\.minimize\(\)/);
  assert.match(mainProcessSource, /mainWindow\.maximize\(\)/);
  assert.match(mainProcessSource, /mainWindow\.unmaximize\(\)/);
  assert.match(mainProcessSource, /mainWindow\.close\(\)/);
  assert.match(bridgeTypes, /windowControls\??:/);
  assert.match(bridgeTypes, /platform\??:/);
});

test('shell grid reserves titlebar and content with an optional recovery row', () => {
  // Healthy runtime connections consume no footer space.
  assert.match(
    chromeStyles,
    /grid-template-rows:\s*36px minmax\(0, 1fr\) auto\s*;/,
  );
  // The same conditional recovery row works without a native titlebar.
  assert.match(
    chromeStyles,
    /grid-template-rows:\s*0 minmax\(0, 1fr\) auto\s*;/,
  );
  // Titlebar and status bar span the full grid width.
  assert.match(chromeStyles, /\.desktop-titlebar\s*\{[\s\S]*?grid-column:\s*1 \/ -1;/);
  assert.match(chromeStyles, /\.desktop-titlebar\s*\{[\s\S]*?grid-row:\s*1;/);
  assert.match(chromeStyles, /\.desktop-status-bar\s*\{[\s\S]*?grid-column:\s*1 \/ -1;/);
  assert.match(chromeStyles, /\.desktop-status-bar\s*\{[\s\S]*?grid-row:\s*3;/);
  // The sidebar yields the titlebar and status bar rows.
  assert.match(sidebarStyles, /\.desktop-design-sidebar\s*\{[\s\S]*?grid-row:\s*2;/);
  // The hierarchy shell no longer collapses the shell into a single row.
  assert.doesNotMatch(
    sidebarStyles,
    /\.app-shell\.hierarchy-shell[^{]*\{[^}]*grid-template-rows:\s*minmax\(0, 1fr\)/,
  );
});

test('titlebar is a drag region with no-drag interactive controls', () => {
  assert.match(titlebarSource, /className="desktop-titlebar"/);
  assert.doesNotMatch(titlebarSource, /className="titlebar"/);
  assert.match(titlebarStyles, /\.desktop-titlebar\s*\{[\s\S]*?-webkit-app-region:\s*drag;/);
  assert.match(titlebarStyles, /-webkit-app-region:\s*no-drag;/);
  // macOS native traffic lights get an inset pad inside the drag region.
  assert.match(titlebarSource, /desktop-titlebar-traffic-pad/);
  // Window controls are rendered for non-darwin native shells only.
  assert.match(titlebarSource, /<WindowControls\s*\/>/);
  assert.match(windowControlsSource, /__MEMSTACK_DESKTOP__\?\.windowControls/);
  assert.match(windowControlsSource, /bridge\.minimize\(\)/);
  // Maximize state is authoritative in the main process: the renderer toggles
  // and confirms through the bridge instead of tracking clicks locally.
  assert.match(windowControlsSource, /bridge\.toggleMaximize\(\)/);
  assert.match(windowControlsSource, /bridge\.isMaximized\(\)/);
  assert.match(windowControlsSource, /bridge\.close\(\)/);
});

test('status bar only exposes unavailable connections with recovery actions', () => {
  assert.match(statusBarSource, /if \(!runtimeUnavailable && liveConnected && !liveError\) return null/);
  assert.match(statusBarSource, /className="desktop-status-bar" role="status" aria-live="polite"/);
  assert.match(statusBarSource, /runtime\.status\.\$\{connection\}/);
  assert.match(statusBarSource, /statusbar\.disconnected/);
  assert.match(statusBarSource, /className="desktop-status-bar-error">\{liveError\}/);
  assert.match(statusBarSource, /onClick=\{onOpenConnectionSettings\}/);
  assert.doesNotMatch(statusBarStyles, /height:\s*24px;/);
});

test('sidebar is partitioned into brand, nav, header, list, and toolbar zones', () => {
  const zones = [
    'desktop-design-brand',
    'desktop-design-primary-nav',
    'desktop-design-header',
    'desktop-design-workspaces',
    'desktop-design-toolbar',
  ];
  let previousIndex = -1;
  for (const zone of zones) {
    const index = sidebarSource.indexOf(`"${zone}"`);
    assert.ok(index > previousIndex, `${zone} must render after the previous zone`);
    previousIndex = index;
  }
  assert.match(sidebarSource, /onClick=\{onOpenSearch\}/);
  assert.doesNotMatch(sidebarSource, /desktop-design-footer-nav/);
  // The bottom toolbar keeps the settings entry next to the profile trigger.
  assert.match(sidebarSource, /desktop-design-toolbar-button/);
  assert.match(
    sidebarStyles,
    /\.desktop-design-toolbar\s*\{[\s\S]*?border-top:\s*0;/,
  );
  assert.match(sidebarStyles, /\.desktop-design-primary-nav\s*\{/);
});

test('sidebar omits summary chips while shell retains authoritative conversation state', () => {
  assert.doesNotMatch(sidebarSource, /className="desktop-conversation-status-summary"/);
  assert.match(sidebarSource, /<WorkspaceDock/);
  assert.match(appSource, /conversationStatusSummary,/);
  assert.doesNotMatch(appSource, /conversationStatusSummary=\{[^}]*conversationsByWorkspace/);
  assert.match(appSource, /conversationStatusScopeRef/);
  assert.match(
    appSource,
    /conversationStatusScopeRef\.current = '';[\s\S]*?setConversationStatusSummary\(null\)/,
  );
  assert.match(
    appSource,
    /\.catch\(\(\) => \{[\s\S]*?conversationStatusScopeRef\.current === requestScope[\s\S]*?setConversationStatusSummary\(null\)/,
  );
});

test('workbench mounts the tab bar above a dedicated content layer', () => {
  assert.equal(
    (authenticatedShellSurfaceSource.match(/<DesktopRendererWorkbenchTabBarV2\b/g) ?? [])
      .length,
    1,
  );
  assert.match(appSource, /tabBar:\s*\{[\s\S]*tabs:\s*openTabs/u);
  assert.match(appSource, /activeTabKey:\s*activeWorkbenchTabKey/);
  assert.match(appSource, /onActivate:\s*activateWorkbenchTab/);
  assert.match(appSource, /onClose:\s*closeWorkbenchTab/);
  // The router subtree stays intact inside the content layer.
  assert.match(
    authenticatedShellSurfaceSource,
    /<div className="workbench-content">[\s\S]*?<DesktopRendererProductionRouterV2/,
  );
  assert.match(workbenchSurfaceSource, /className="workbench-layout"/);
});

test('workbench grid reserves a 32px tab row', () => {
  assert.match(
    chromeStyles,
    /\.workbench\s*\{[\s\S]*?grid-template-rows:\s*32px minmax\(0, 1fr\)/,
  );
  assert.match(chromeStyles, /\.workbench-content\s*\{/);
  assert.match(tabBarStyles, /\.workbench-tab-bar\s*\{[\s\S]*?height:\s*32px;/);
  assert.match(tabBarStyles, /\.workbench-tab-bar\s*\{[\s\S]*?border-bottom:/);
});

test('tab state flows through the pure workbench tab model', () => {
  for (const fn of [
    'ensureViewTab',
    'ensureConversationTab',
    'closeTab',
    'clearConversationTabs',
    'tabKey',
    'isSameTab',
  ]) {
    assert.match(tabBarModelSource, new RegExp(`export function ${fn}\\b`), `${fn} exported`);
  }
  // View tabs open through the section funnel; conversation tabs sync from
  // the scoped conversation; scope resets drop conversation tabs.
  assert.match(appSource, /isViewTabSection\(section\)[\s\S]*?ensureViewTab\(tabs, section\)/);
  assert.match(appSource, /ensureConversationTab\(tabs, \{[\s\S]*?scopedConversation\.id/);
  assert.match(appSource, /setOpenTabs\(\(tabs\) => clearConversationTabs\(tabs\)\)/);
});

test('the retired tab bar renders nothing while preserving the conversation callback interface', () => {
  assert.match(tabBarSource, /return null/);
  assert.doesNotMatch(tabBarSource, /role="tablist"|role="tab"/);
  assert.match(tabBarSource, /onActivate:/);
  assert.match(tabBarSource, /onClose:/);
});

test('right sidebar hosts opened work tabs through a single header', () => {
  assert.equal(
    (authenticatedShellSurfaceSource.match(/<DesktopRendererRightSidebarV2\b/g) ?? []).length,
    1,
  );
  assert.equal((rightSidebarSurfaceSource.match(/<DesktopRightSidebar\b/g) ?? []).length, 1);
  assert.doesNotMatch(authenticatedShellSurfaceSource, /<DesktopRightSidebar\b/u);
  // Only rendered for chat sessions, and the titlebar toggle greys out otherwise.
  assert.match(appSource, /rightSidebarAvailable[\s\S]*?activeSection === 'chat'/);
  assert.match(
    appSource,
    /rightSidebarAvailable && rightSidebarOpen[\s\S]*?kind:\s*'visible'/u,
  );
  assert.match(appSource, /rightSidebarAvailable,/);
  assert.match(
    authenticatedShellSurfaceSource,
    /surfaces\.rightSidebar\.kind === 'visible'[\s\S]*<DesktopRendererRightSidebarV2/u,
  );
  // The shell owns navigation; embedded canvas renders only content.
  assert.doesNotMatch(rightSidebarSource, /desktop-right-activity-bar/);
  assert.match(rightSidebarSource, /state\.tabs\.map/);
  assert.match(rightSidebarSource, /role="tablist"/);
  assert.match(rightSidebarSource, /rightbar\.addView/);
  assert.match(rightSidebarSource, /disabled=\{!entry\.available\}/);
  assert.match(rightSidebarSource, /<DesktopRendererSessionCanvasV2/u);
  assert.match(rightSidebarSource, /embedded: true/);
  assert.match(rightSidebarSource, /<SessionContextRail/);
  assert.match(rightSidebarSource, /<BrowserPanel/);
  // Width derives from usable space; expansion preserves the preferred width.
  assert.match(rightSidebarSource, /workPanelGeometry\(availableWidth, preferredWidth, focused\)/);
  assert.match(rightSidebarSource, /setFocused\(\(value\) => !value\)/);
  assert.match(appSource, /rightPanels\.restoreFocus\(\)/);

});

test('shell grid adds a self-sizing third column for the right sidebar', () => {
  assert.match(
    chromeStyles,
    /grid-template-columns:\s*var\(--desktop-sidebar-width\) minmax\(0, 1fr\) auto;/,
  );
  assert.match(rightSidebarStyles, /\.desktop-right-sidebar\s*\{[\s\S]*?grid-column:\s*3;/);
  assert.match(rightSidebarStyles, /\.desktop-right-sidebar\s*\{[\s\S]*?grid-row:\s*2;/);
  assert.match(chromeStyles, /\.desktop-right-sidebar\s*\{\s*display:\s*none;/);
});

test('SessionWorkspace keeps only the thread column after the rail migration', () => {
  assert.doesNotMatch(sessionWorkspaceSource, /sessionLayoutModel/);
  assert.doesNotMatch(sessionWorkspaceSource, /session-context-rail/);
  assert.doesNotMatch(sessionWorkspaceSource, /canvasRevealKey|onCloseCanvas/);
  assert.match(sessionWorkspaceSource, /className="session-workspace-body"/);
  assert.match(sessionWorkspaceSource, /onOpenCanvas\('overview'\)/);
});

test('titlebar and status bar copy exists in both locales', () => {
  for (const key of [
    'titlebar.toggleSidebar',
    'titlebar.toggleRightPanel',
    'titlebar.minimize',
    'titlebar.maximize',
    'titlebar.restore',
    'titlebar.close',
    'statusbar.runtime',
    'statusbar.live',
    'statusbar.connected',
    'statusbar.disconnected',
    'overview.conversations',
    'tabs.bar',
    'tabs.close',
    'rightbar.context',
    'rightbar.canvas',
    'rightbar.browser',
    'rightbar.close',
    'rightbar.resize',
  ]) {
    assert.equal(
      i18nSource.match(new RegExp(`'${key.replace('.', '\\.')}'`, 'g'))?.length,
      2,
      `${key} must exist in both locales`,
    );
  }
});


test('workbench content stays in the flexible row when a single conversation hides tabs', () => {
  assert.match(chromeStyles, /\.workbench\s*\{[^}]*grid-template-rows:\s*0 minmax\(0, 1fr\)/);
  assert.match(chromeStyles, /\.workbench:has\(> \.workbench-tab-bar\)\s*\{[^}]*grid-template-rows:\s*32px minmax\(0, 1fr\)/);
  assert.match(chromeStyles, /\.workbench-content\s*\{[^}]*grid-row:\s*2;/);
});
