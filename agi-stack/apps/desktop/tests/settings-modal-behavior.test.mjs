import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const settingsWindowSource = readFileSync(
  new URL('../src/features/settings/SettingsWindow.tsx', import.meta.url),
  'utf8'
);
const addProviderSource = readFileSync(
  new URL('../src/features/settings/AddProviderDialog.tsx', import.meta.url),
  'utf8'
);
const providerModelsSource = readFileSync(
  new URL('../src/features/settings/ProviderModelsPanel.tsx', import.meta.url),
  'utf8'
);
const providerWorkspaceSource = readFileSync(
  new URL('../src/features/settings/ModelProviderWorkspace.tsx', import.meta.url),
  'utf8'
);
const providerConnectionSource = readFileSync(
  new URL('../src/features/settings/ProviderConnectionPanel.tsx', import.meta.url),
  'utf8'
);
const modalDialogSource = readFileSync(
  new URL('../src/features/settings/useModalDialog.ts', import.meta.url),
  'utf8'
);

test('settings dialogs trap focus, restore focus, and give nested Escape priority', () => {
  assert.match(modalDialogSource, /previouslyFocused/);
  assert.match(modalDialogSource, /event\.key !== 'Tab'/);
  assert.match(modalDialogSource, /stopImmediatePropagation\(\)/);
  assert.match(modalDialogSource, /capture: nested/);
  assert.match(settingsWindowSource, /useModalDialog\(\{[\s\S]*active: open/);
  assert.match(addProviderSource, /useModalDialog\(\{[\s\S]*nested: true/);
  assert.match(
    addProviderSource,
    new RegExp(
      'className="provider-dialog-backdrop"[\\s\\S]{0,180}' +
        'event\\.stopPropagation\\(\\)[\\s\\S]{0,80}onClose\\(\\)'
    )
  );
  assert.doesNotMatch(settingsWindowSource, /window\.addEventListener\('keydown'/);
  assert.doesNotMatch(addProviderSource, /window\.addEventListener\('keydown'/);
});

test('provider catalog requests ignore stale responses after a provider change', () => {
  assert.match(addProviderSource, /catalogRequestId/);
  assert.match(
    addProviderSource,
    /requestId !== catalogRequestId\.current[\s\S]*return/
  );
  assert.match(providerModelsSource, /catalogRequestId/);
  assert.match(
    providerModelsSource,
    /requestId !== catalogRequestId\.current[\s\S]*return/
  );
});

test('provider validation results cannot verify a newer draft or clear newer work', () => {
  assert.match(addProviderSource, /validationRequestId/);
  assert.match(addProviderSource, /invalidateValidation/);
  assert.match(
    addProviderSource,
    /requestId !== validationRequestId\.current[\s\S]*return/
  );
  assert.match(
    addProviderSource,
    /requestId === validationRequestId\.current[\s\S]*setBusy\(null\)/
  );
});

test('provider saves cannot report into or steal selection from a newer provider', () => {
  assert.match(providerModelsSource, /saveRequestId/);
  assert.match(providerModelsSource, /activeProviderIdRef/);
  assert.match(
    providerModelsSource,
    /providerId !== activeProviderIdRef\.current[\s\S]*return/
  );
  const replaceProvider = providerWorkspaceSource.match(
    /const replaceProvider = useCallback\([\s\S]*?\n  \}, \[\]\);/
  );
  assert.ok(replaceProvider, 'replaceProvider callback should remain explicit');
  assert.doesNotMatch(replaceProvider[0], /setSelectedId/);
});

test('provider connection state and requests reset at the provider identity boundary', () => {
  assert.match(providerConnectionSource, /activeProviderIdRef/);
  assert.match(providerConnectionSource, /validationRequestId/);
  assert.match(providerConnectionSource, /saveRequestId/);
  assert.match(
    providerConnectionSource,
    /useEffect\(\(\) => \{[\s\S]*providerDraftFromProvider\(provider\)[\s\S]*\}, \[provider\.id\]\)/
  );
  const saveConnection = providerConnectionSource.match(
    /const saveConnection = async \(\) => \{[\s\S]*?\n  \};/
  );
  assert.ok(saveConnection, 'saveConnection should remain an explicit request boundary');
  assert.match(saveConnection[0], /apiKey: ''[\s\S]*setValidation\(null\)/);
});
