import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
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
const auxiliaryViewUrl = new URL('../src/features/navigation/AuxiliaryView.tsx', import.meta.url);
const auxiliaryViewStylesUrl = new URL(
  '../src/features/navigation/AuxiliaryView.css',
  import.meta.url,
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

  assert.match(appSource, /from '\.\/features\/navigation\/AuxiliaryView'/);
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
  assert.match(appSource, /<AuxiliaryView/);
});

test('auxiliary navigation uses the shared prototype overview surface', () => {
  assert.equal(existsSync(auxiliaryViewUrl), true);
  assert.equal(existsSync(auxiliaryViewStylesUrl), true);
  if (!existsSync(auxiliaryViewUrl) || !existsSync(auxiliaryViewStylesUrl)) return;

  const auxiliaryViewSource = readFileSync(auxiliaryViewUrl, 'utf8');
  const auxiliaryViewStyles = readFileSync(auxiliaryViewStylesUrl, 'utf8');
  assert.doesNotMatch(auxiliaryViewSource, /AuxiliarySection|section:/u);
  assert.doesNotMatch(auxiliaryViewSource, /LightningBoltIcon|MagnifyingGlassIcon/u);
  assert.match(auxiliaryViewSource, /className="auxiliary-view"/);
  assert.doesNotMatch(auxiliaryViewSource, /<main className="auxiliary-view"/);
  assert.match(auxiliaryViewSource, /onOpenMyWork/);
  assert.match(auxiliaryViewSource, /useI18n\(\)/);
  assert.match(auxiliaryViewSource, /import '\.\/AuxiliaryView\.css'/);
  assert.match(auxiliaryViewStyles, /\.auxiliary-view\s*\{/);
  assert.match(auxiliaryViewStyles, /\.overview-grid\s*\{/);
  assert.match(auxiliaryViewStyles, /grid-template-columns:\s*2fr 1fr 1fr/);
});

test('Work and Code mode controls live in the new-thread composer', () => {
  assert.match(workbenchSurfaceSource, /<NewThreadComposer/u);
  assert.doesNotMatch(appSource, /<NewThreadComposer/u);
  assert.match(appSource, /onModeChange:\s*setPreferredTaskMode/u);
  assert.doesNotMatch(appSource, /setPreferredTaskMode\(mode\)[\s\S]*switchSection\('board'\)/);
});
