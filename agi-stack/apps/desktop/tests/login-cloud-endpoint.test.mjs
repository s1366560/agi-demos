import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = '/tmp/agistack-desktop-test-dist/src';
const { I18nProvider } = require(`${root}/i18n.js`);
const { LoginScreen } = require(`${root}/features/auth/LoginScreen.js`);
const { useLocalCredentialAuth } = require(`${root}/hooks/useLocalCredentialAuth.js`);
const { DEFAULT_CONFIG } = require(`${root}/types.js`);
const { emptyAuthState } = require(`${root}/appShellTypes.js`);
const noop = () => {};
const endpoint = 'http://127.0.0.1:18766';

function renderLogin(overrides = {}) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(LoginScreen, {
        auth: emptyAuthState,
        cloudApiBaseUrl: endpoint,
        onCloudApiBaseUrlChange: noop,
        email: '',
        password: '',
        onEmailChange: noop,
        onPasswordChange: noop,
        onEmailLogin: noop,
        onWorkspaceSso: noop,
        nativeOAuthProviders: [],
        nativeOAuthPendingProvider: null,
        onNativeOAuth: noop,
        workspaceSso: null,
        onOpenWorkspaceSso: noop,
        onCancelWorkspaceSso: noop,
        ...overrides,
      }),
    ),
  );
}

function endpointInput(html) {
  return html.match(/<input[^>]*aria-label="Server URL"[^>]*>/u)?.[0];
}

test('sign-in exposes the cloud server URL and a retired local session notice', () => {
  const input = endpointInput(renderLogin());
  assert.ok(input, 'Cloud sign-in must expose Server URL');
  assert.match(input, /type="url"/u);
  assert.match(input, /value="http:\/\/127\.0\.0\.1:18766"/u);
  assert.doesNotMatch(input, /disabled/u);
  const html = renderLogin();
  assert.doesNotMatch(html, /Local workspace|本地工作区|desktop-login-mode/u);
  assert.match(html, /Continue with workspace SSO|使用工作区 SSO 继续/u);
  assert.match(
    renderLogin({ legacyLocalLoginNotice: true }),
    /Local workspace sign-in was removed|本地工作区登录已移除/u,
  );
});

test('Cloud endpoint cannot change while sign-in is pending', () => {
  const input = endpointInput(
    renderLogin({
      auth: { ...emptyAuthState, status: 'signing_in' },
    }),
  );
  assert.ok(input);
  assert.match(input, /disabled=""/u);
});

function authHarness(initialConfig) {
  const configRef = { current: initialConfig };
  const params = {
    runsInNativeDesktop: true,
    config: initialConfig,
    auth: emptyAuthState,
    loginEmail: '',
    loginPassword: '',
    configRef,
    localResumeAttemptRef: { current: '' },
    authAttemptRevisionRef: { current: 0 },
    commitRuntimeConfig(value) {
      configRef.current = value;
    },
    setLoginEmail: noop,
    setLoginPassword: noop,
    setAuth: noop,
    setConnection: noop,
    setError: noop,
    setAgentConversationSession: noop,
    setAgentTaskSignals: noop,
    resetProjectScopedState: noop,
    resetConversationTimeline: noop,
  };
  let handlers;
  function Capture() {
    handlers = useLocalCredentialAuth(params, { supersedeWorkspaceSsoAttempt: noop });
    return null;
  }
  renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(Capture)));
  return { configRef, handlers };
}

test('editing the cloud endpoint does not reseed a local workspace', () => {
  const { configRef, handlers } = authHarness({
    ...DEFAULT_CONFIG,
    mode: 'cloud',
    apiBaseUrl: 'http://127.0.0.1:8000',
    tenantId: 'default',
    projectId: '',
  });
  handlers.handleConfigChange({ ...configRef.current, apiBaseUrl: endpoint });
  assert.equal(configRef.current.apiBaseUrl, endpoint);
  assert.equal(configRef.current.mode, 'cloud');
  assert.notEqual(configRef.current.tenantId, 'local');
  assert.notEqual(configRef.current.projectId, 'local-project');
});
