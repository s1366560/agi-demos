import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');
const sidebarSource = readFileSync(
  new URL('../src/features/navigation/DesktopSidebar.tsx', import.meta.url),
  'utf8',
);
const rendererArtifactCatalogSource = readFileSync(
  new URL('../src/plugins/desktopRendererArtifactCatalogV2.ts', import.meta.url),
  'utf8',
);
const workbenchSurfaceSource = readFileSync(
  new URL('../src/plugins/DesktopWorkbenchSurfaceV2.tsx', import.meta.url),
  'utf8',
);
test('only shell-owned views remain first-class workbench sections', () => {
  const workbenchSection = typesSource.match(/export type WorkbenchSection =[\s\S]*?;/)?.[0] ?? '';

  assert.match(workbenchSection, /'home'/);
  assert.match(workbenchSection, /'board'/);
  assert.match(workbenchSection, /'activity'/);
  assert.doesNotMatch(workbenchSection, /'search'/);
  assert.doesNotMatch(workbenchSection, /'automations'/);
});

test('Search and Automations enter only through V2 route and navigation contributions', () => {
  const navigationHandler =
    appSource.match(/onNavigate:\s*\(section\) => \{[\s\S]*?\n\s*\},/)?.[0] ?? '';
  const primaryItems =
    sidebarSource.match(/const primaryItems = \[[\s\S]*?\] as const;/u)?.[0] ?? '';
  const selectWorkbenchView =
    appSource.match(/const selectDesktopWorkbenchViewV2 = [\s\S]*?\n  \};/u)?.[0] ?? '';

  assert.doesNotMatch(appSource, /from '\.\/features\/navigation\/AuxiliaryView'/);
  assert.match(navigationHandler, /section === 'home'[\s\S]*switchSection\('home'\)/);
  assert.doesNotMatch(navigationHandler, /section === '(?:automations|search)'/u);
  assert.doesNotMatch(navigationHandler, /openWorkspaceOverview|openCommandPalette/);
  assert.doesNotMatch(primaryItems, /id: '(?:automations|search)'/u);

  assert.match(selectWorkbenchView, /activeSection === 'home'/);
  assert.doesNotMatch(selectWorkbenchView, /activeSection === '(?:automations|search)'/u);
  assert.doesNotMatch(appSource, /LazyAutomationsPage|renderAutomationsPage/u);
  assert.doesNotMatch(appSource, /features\/automations\/AutomationsPage/u);
  assert.doesNotMatch(appSource, /DesktopSearch|renderSearchPage/u);
  assert.match(appSource, /const routeCommandItems: CommandPaletteItem\[\]/u);
  assert.match(appSource, /desktopCanonicalNavigationRegistry/u);
  assert.match(rendererArtifactCatalogSource, /PROJECT_CRON_JOBS_ROUTE_ID/u);
  assert.match(rendererArtifactCatalogSource, /PROJECT_SEARCH_ROUTE_ID/u);
  assert.doesNotMatch(appSource, /<AuxiliaryView/u);
});

test('Work and Code mode controls live in the new-thread composer', () => {
  assert.match(workbenchSurfaceSource, /<DesktopRendererNewThreadComposerV2/u);
  assert.doesNotMatch(workbenchSurfaceSource, /<NewThreadComposer/u);
  assert.doesNotMatch(appSource, /<NewThreadComposer/u);
  assert.match(appSource, /onModeChange:\s*setPreferredTaskMode/u);
  assert.doesNotMatch(appSource, /setPreferredTaskMode\(mode\)[\s\S]*switchSection\('board'\)/);
});
