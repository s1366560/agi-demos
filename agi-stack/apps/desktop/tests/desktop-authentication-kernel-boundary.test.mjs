import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const auxiliaryViewSource = new URL(
  '../src/features/navigation/AuxiliaryView.tsx',
  import.meta.url,
);
const auxiliaryViewStyles = new URL(
  '../src/features/navigation/AuxiliaryView.css',
  import.meta.url,
);

test('authentication stays kernel-owned and App drops its dead auxiliary view', () => {
  const forcedPasswordGate = appSource.lastIndexOf("auth.status === 'password_change_required'");
  const anonymousGate = appSource.indexOf('if (!identityAuthenticated)', forcedPasswordGate);
  const forcedPasswordSource = appSource.slice(forcedPasswordGate, anonymousGate);
  const authenticatedBoundary = appSource.indexOf('\n  const activeTenantName =', anonymousGate);
  const anonymousSource = appSource.slice(anonymousGate, authenticatedBoundary);

  assert.ok(forcedPasswordGate >= 0);
  assert.ok(anonymousGate > forcedPasswordGate);
  assert.ok(authenticatedBoundary > anonymousGate);
  assert.match(forcedPasswordSource, /<ForcePasswordChangeScreen\b/u);
  assert.doesNotMatch(
    forcedPasswordSource,
    /DesktopRendererGenerationProviderV2|DesktopRendererAuthenticationRouterV2/u,
  );
  assert.match(
    anonymousSource,
    /<DesktopRendererGenerationProviderV2[\s\S]*<DesktopRendererAuthenticationRouterV2[\s\S]*<LoginScreen\b/u,
  );
  assert.doesNotMatch(appSource, /import \{ AuxiliaryView \}/u);
  assert.doesNotMatch(appSource, /\bconst renderAuxiliaryView\s*=/u);
  assert.equal(existsSync(auxiliaryViewSource), false);
  assert.equal(existsSync(auxiliaryViewStyles), false);
});
