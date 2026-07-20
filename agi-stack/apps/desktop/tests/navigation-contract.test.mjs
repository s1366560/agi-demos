import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');
const auxiliaryViewUrl = new URL(
  '../src/features/navigation/AuxiliaryView.tsx',
  import.meta.url,
);
const auxiliaryViewStylesUrl = new URL(
  '../src/features/navigation/AuxiliaryView.css',
  import.meta.url,
);

test('Home, Search, and Automations are first-class workbench sections', () => {
  const workbenchSection =
    typesSource.match(/export type WorkbenchSection =[\s\S]*?;/)?.[0] ?? '';

  assert.match(workbenchSection, /'home'/);
  assert.match(workbenchSection, /'search'/);
  assert.match(workbenchSection, /'automations'/);
});

test('primary navigation opens section-based auxiliary views', () => {
  const navigationHandler =
    appSource.match(/onNavigate=\{\(section\) => \{[\s\S]*?\n\s*\}\}/)?.[0] ?? '';
  const renderWorkbench =
    appSource.match(
      /const renderWorkbench = [\s\S]*?\n  \};\n\n  if \(!identityAuthenticated\)/,
    )?.[0] ?? '';

  assert.match(appSource, /from '\.\/features\/navigation\/AuxiliaryView'/);
  assert.match(navigationHandler, /section === 'home'[\s\S]*switchSection\('home'\)/);
  assert.match(
    navigationHandler,
    /section === 'automations'[\s\S]*switchSection\('automations'\)/,
  );
  assert.match(navigationHandler, /section === 'search'[\s\S]*switchSection\('search'\)/);
  assert.doesNotMatch(navigationHandler, /openWorkspaceOverview|openCommandPalette/);

  assert.match(renderWorkbench, /activeSection === 'home'/);
  assert.match(renderWorkbench, /activeSection === 'automations'/);
  assert.match(renderWorkbench, /activeSection === 'search'/);
  assert.match(appSource, /from '\.\/features\/automations\/AutomationsPage'/);
  assert.match(appSource, /<AutomationsPage/);
  assert.match(appSource, /<AuxiliaryView/);
  assert.match(renderWorkbench, /(?:<AuxiliaryView|renderAuxiliaryView)/);
  assert.match(renderWorkbench, /renderAutomationsPage/);
});

test('auxiliary navigation uses the shared prototype overview surface', () => {
  assert.equal(existsSync(auxiliaryViewUrl), true);
  assert.equal(existsSync(auxiliaryViewStylesUrl), true);
  if (!existsSync(auxiliaryViewUrl) || !existsSync(auxiliaryViewStylesUrl)) return;

  const auxiliaryViewSource = readFileSync(auxiliaryViewUrl, 'utf8');
  const auxiliaryViewStyles = readFileSync(auxiliaryViewStylesUrl, 'utf8');
  assert.match(
    auxiliaryViewSource,
    /export type AuxiliarySection = 'home' \| 'automations' \| 'search'/,
  );
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
  assert.match(appSource, /<NewThreadComposer/);
  assert.match(appSource, /onModeChange=\{setPreferredTaskMode\}/);
  assert.doesNotMatch(appSource, /setPreferredTaskMode\(mode\)[\s\S]*switchSection\('board'\)/);
});
