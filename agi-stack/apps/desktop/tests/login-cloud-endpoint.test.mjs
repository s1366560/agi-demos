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
        mode: 'cloud',
        localReady: true,
        cloudApiBaseUrl: endpoint,
        onCloudApiBaseUrlChange: noop,
        email: '',
        password: '',
        onModeChange: noop,
        onEmailChange: noop,
        onPasswordChange: noop,
        onEmailLogin: noop,
        onLocalSession: noop,
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

test('Cloud sign-in exposes the controlled server URL and Local keeps its endpoint hidden', () => {
  const input = endpointInput(renderLogin());
  assert.ok(input, 'Cloud sign-in must expose Server URL');
  assert.match(input, /type="url"/u);
  assert.match(input, /value="http:\/\/127\.0\.0\.1:18766"/u);
  assert.doesNotMatch(input, /disabled/u);
  assert.equal(endpointInput(renderLogin({ mode: 'local' })), undefined);
  assert.ok(endpointInput(renderLogin({ mode: 'local', localModeAvailable: false })));
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

test('the active auth hook retains an edited Cloud endpoint across Local and Cloud mode changes', () => {
  const { configRef, handlers } = authHarness({ ...DEFAULT_CONFIG, mode: 'local' });
  handlers.changeLoginMode('cloud');
  assert.equal(configRef.current.apiBaseUrl, 'http://127.0.0.1:8000');
  handlers.handleConfigChange({ ...configRef.current, apiBaseUrl: endpoint });
  handlers.changeLoginMode('local');
  assert.equal(configRef.current.apiBaseUrl, 'http://127.0.0.1:8088');
  assert.equal(configRef.current.tenantId, 'local');
  handlers.changeLoginMode('cloud');
  assert.equal(configRef.current.apiBaseUrl, endpoint);
  assert.equal(configRef.current.tenantId, 'default');
  assert.equal(configRef.current.apiKey, '');
  assert.equal(configRef.current.localApiToken, '');
});

test('a restored Cloud endpoint survives mode changes without persisting a separate URL preference', () => {
  const { configRef, handlers } = authHarness({
    ...DEFAULT_CONFIG,
    mode: 'cloud',
    apiBaseUrl: endpoint,
  });
  handlers.changeLoginMode('local');
  handlers.changeLoginMode('cloud');
  assert.equal(configRef.current.apiBaseUrl, endpoint);
});
