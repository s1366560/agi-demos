import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const i18nModulePath = require.resolve('/tmp/agistack-desktop-test-dist/src/i18n.js');

test('an existing provider remains compatible with consumers after i18n hot reload', () => {
  const { I18nProvider } = require(i18nModulePath);

  delete require.cache[i18nModulePath];
  const { useI18n } = require(i18nModulePath);

  function ReloadedConsumer() {
    const { t } = useI18n();
    return React.createElement('span', null, t('settings.empty'));
  }

  assert.doesNotThrow(() =>
    renderToStaticMarkup(
      React.createElement(I18nProvider, null, React.createElement(ReloadedConsumer)),
    ),
  );
});
