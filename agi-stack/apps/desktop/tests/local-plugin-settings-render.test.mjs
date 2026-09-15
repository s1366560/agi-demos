import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const {
  LocalPluginSettings,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/LocalPluginSettings.js');
const { I18nContext } = require('/tmp/agistack-desktop-test-dist/src/i18nContext.js');
function render(config, canManage = true) {
  return renderToStaticMarkup(
    React.createElement(
      I18nContext.Provider,
      { value: { locale: 'en', setLocale() {}, t: (key) => key } },
      React.createElement(LocalPluginSettings, { config, canManage }),
    ),
  );
}

test('local plugin panel cannot offer approval or active plugins before host verification', () => {
  const markup = render({
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  });
  assert.match(markup, /tenant-1 \/ project-1/);
  assert.match(markup, /disabled="">localPlugins.choose/);
  assert.doesNotMatch(markup, /localPlugins.install|localPlugins.confirmed|localPlugins.enabled/);
  assert.doesNotMatch(markup, /type="file"|\.pem|trusted_keys/);
});

test('missing project remains a clear disabled native import boundary', () => {
  const markup = render({ mode: 'local', tenantId: 'tenant-1', projectId: '' });
  assert.match(markup, /localPlugins.noScope/);
  assert.match(markup, /disabled="">localPlugins.choose/);
});
