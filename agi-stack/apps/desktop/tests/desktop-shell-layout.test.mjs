import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
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
  assert.equal((appSource.match(/<DesktopTitlebar\b/g) ?? []).length, 1);
  assert.equal((appSource.match(/<DesktopStatusBar\b/g) ?? []).length, 1);
  // The titlebar only renders inside the native desktop window shell.
  assert.match(
    appSource,
    /runsInNativeDesktop \? \([\s\S]*?<DesktopTitlebar/,
  );
  // The right sidebar toggle state is owned by the shell for later phases.
  assert.match(appSource, /const \[rightSidebarOpen, setRightSidebarOpen\] = useState\(true\)/);
  assert.match(appSource, /rightSidebarOpen=\{rightSidebarOpen\}/);
  assert.match(appSource, /onToggleRightSidebar=\{/);
  // The titlebar reuses the existing sidebar collapse state.
  assert.match(appSource, /sidebarCollapsed=\{sidebarCollapsed\}/);
  assert.match(appSource, /onToggleSidebar=\{/);
});

test('main window is frameless with platform-specific titlebar styles', () => {
  assert.match(mainProcessSource, /titleBarStyle:\s*'hiddenInset'/);
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

test('shell grid reserves a titlebar row and a status bar row', () => {
  // Native shell: 36px titlebar, flexible content, 24px status bar.
  assert.match(
    chromeStyles,
    /grid-template-rows:\s*36px minmax\(0, 1fr\) 24px\s*;/,
  );
  // Browser shell: no titlebar, content, 24px status bar.
  assert.match(
    chromeStyles,
    /grid-template-rows:\s*0 minmax\(0, 1fr\) 24px\s*;/,
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
  assert.match(windowControlsSource, /bridge\.maximize\(\)/);
  assert.match(windowControlsSource, /bridge\.unmaximize\(\)/);
  assert.match(windowControlsSource, /bridge\.close\(\)/);
});

test('status bar surfaces runtime, socket, and scope context', () => {
  assert.match(statusBarSource, /className="desktop-status-bar"/);
  assert.match(statusBarSource, /t\(`runtime\.status\.\$\{connection\}`\)/);
  assert.match(statusBarSource, /statusbar\.live/);
  assert.match(statusBarSource, /statusbar\.connected/);
  assert.match(statusBarSource, /statusbar\.disconnected/);
  assert.match(statusBarSource, /title=\{liveError \?\? undefined\}/);
  assert.match(statusBarSource, /\{tenantName\}/);
  assert.match(statusBarSource, /\{projectName\}/);
  assert.match(statusBarStyles, /\.desktop-status-bar\s*\{[\s\S]*?height:\s*24px;/);
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
  // Activity moved from the retired footer nav into the primary view nav.
  assert.match(
    sidebarSource,
    /\{ id: 'activity', labelKey: 'sidebar\.activity', icon: BellIcon \}/,
  );
  assert.doesNotMatch(sidebarSource, /desktop-design-footer-nav/);
  // The bottom toolbar keeps the settings entry next to the profile trigger.
  assert.match(sidebarSource, /desktop-design-toolbar-button/);
  assert.match(
    sidebarStyles,
    /\.desktop-design-toolbar\s*\{[\s\S]*?border-top:\s*1px solid/,
  );
  assert.match(sidebarStyles, /\.desktop-design-primary-nav\s*\{[\s\S]*?border-bottom:/);
});

test('workbench mounts the tab bar above a dedicated content layer', () => {
  assert.equal((appSource.match(/<WorkbenchTabBar\b/g) ?? []).length, 1);
  assert.match(appSource, /tabs=\{openTabs\}/);
  assert.match(appSource, /activeTabKey=\{activeWorkbenchTabKey\}/);
  assert.match(appSource, /onActivate=\{activateWorkbenchTab\}/);
  assert.match(appSource, /onClose=\{closeWorkbenchTab\}/);
  // The router subtree stays intact inside the content layer.
  assert.match(
    appSource,
    /<div className="workbench-content">[\s\S]*?<DesktopProductionRouter/,
  );
  assert.match(appSource, /className="workbench-layout"/);
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

test('tab bar exposes localized activation and close controls', () => {
  assert.match(tabBarSource, /role="tablist"/);
  assert.match(tabBarSource, /role="tab"/);
  assert.match(tabBarSource, /aria-selected=\{active\}/);
  assert.match(tabBarSource, /aria-label=\{t\('tabs\.close'\)\}/);
  assert.match(tabBarSource, /t\('session\.untitled'\)/);
});

test('right sidebar hosts the context rail and canvas behind an activity bar', () => {
  assert.equal((appSource.match(/<DesktopRightSidebar\b/g) ?? []).length, 1);
  // Only rendered for chat sessions, and the titlebar toggle greys out otherwise.
  assert.match(appSource, /rightSidebarAvailable[\s\S]*?activeSection === 'chat'/);
  assert.match(appSource, /rightSidebarAvailable && rightSidebarOpen[\s\S]*?<DesktopRightSidebar/);
  assert.match(appSource, /rightSidebarAvailable=\{rightSidebarAvailable\}/);
  // Activity bar: context and canvas entries with pressed state, canvas can disable.
  assert.match(rightSidebarSource, /desktop-right-activity-bar/);
  assert.equal((rightSidebarSource.match(/aria-pressed=\{activePanel ===/g) ?? []).length, 2);
  assert.match(rightSidebarSource, /disabled=\{!canvasAvailable\}/);
  assert.match(rightSidebarSource, /<SessionContextRail/);
  // Canvas layout maps to panel width: focus widens, split restores default.
  assert.match(rightSidebarSource, /layout === 'focus'\) panelWidth\.resize\(/);
  assert.match(rightSidebarSource, /panelWidth\.reset\(\)/);
  // Closing the canvas restores focus to the originating trigger.
  assert.match(rightSidebarSource, /data-session-canvas-trigger/);
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
  assert.match(sessionWorkspaceSource, /onOpenCanvas=\{onOpenCanvas\}|onOpenCanvas\(\)/);
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
    'tabs.bar',
    'tabs.close',
    'rightbar.context',
    'rightbar.canvas',
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
