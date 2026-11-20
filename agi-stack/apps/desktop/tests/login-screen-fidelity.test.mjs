import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const desktopAuthSource = [
  '../src/hooks/useDesktopAuth.ts',
  '../src/hooks/useCloudSessionAuth.ts',
  '../src/hooks/useLocalCredentialAuth.ts',
]
  .map((path) => readFileSync(new URL(path, import.meta.url), 'utf8'))
  .join('\n');
const loginSource = readFileSync(
  new URL('../src/features/auth/LoginScreen.tsx', import.meta.url),
  'utf8'
);
const loginStyles = readFileSync(
  new URL('../src/features/auth/LoginScreen.css', import.meta.url),
  'utf8'
);
const loginRuntimeSource = readFileSync(
  new URL('../src/features/auth/loginRuntimeModel.ts', import.meta.url),
  'utf8'
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');
const cloudAuthAuthoritySource = readFileSync(
  new URL('../electron/main/cloudAuthenticationAuthority.ts', import.meta.url),
  'utf8',
);

test('approved email path owns the trusted-device choice and inline alert', () => {
  assert.match(loginSource, /onEmailLogin: \(trustedDevice: boolean\) => void/);
  assert.match(loginSource, /onEmailLogin\(trustedDevice\)/);
  assert.match(loginSource, /validateLoginCredentials\(email, password\)/);
  assert.match(loginSource, /<form[\s\S]*noValidate/);
  assert.match(loginSource, /role="alert"/);
  assert.match(loginSource, /t\('login\.invalidCredentials'\)/);
});

test('login keeps cloud email, device, and OAuth entry points without a local workspace switch', () => {
  assert.match(loginSource, /onEmailLogin: \(trustedDevice: boolean\) => void/);
  assert.match(loginSource, /onWorkspaceSso: \(trustedDevice: boolean\) => void/);
  assert.match(loginSource, /onNativeOAuth: \(provider: string, trustedDevice: boolean\) => void/);
  assert.match(loginSource, /legacyLocalLoginNotice/);
  assert.match(loginSource, /t\('login\.legacyLocalSessionCleared'\)/);
  assert.match(loginSource, /type="email"/);
  assert.doesNotMatch(loginSource, /onLocalSession|onModeChange|login\.modeLocal|desktop-login-mode/);
  assert.doesNotMatch(appSource, /onLocalSession|changeLoginMode|loginLocalSession/);
});

test('browser fallback uses the cloud runtime for email login and workspace SSO', () => {
  assert.match(
    appSource,
    /initialDesktopRuntimeConfig\(\)/,
  );
  const ssoHandler = desktopAuthSource.slice(
    desktopAuthSource.indexOf('const loginWithWorkspaceSso'),
    desktopAuthSource.indexOf('const login = async'),
  );
  const emailHandler = desktopAuthSource.slice(
    desktopAuthSource.indexOf('const login = async'),
    desktopAuthSource.indexOf('const handleConfigChange'),
  );
  assert.match(
    ssoHandler,
    /runtimeConfigForLoginAvailability\(configRef\.current\)/,
  );
  assert.match(ssoHandler, /new DesktopApiClient\(\{ \.\.\.runtimeConfig, apiKey: '' \}\)/);
  assert.match(
    emailHandler,
    /runtimeConfigForLoginAvailability\(\s*configRef\.current\s*\)/,
  );
  assert.match(emailHandler, /new DesktopApiClient\(\{ \.\.\.runtimeConfig, apiKey: '' \}\)/);
  assert.match(emailHandler, /hydrateCloudSession\(outcome, runtimeConfig, authAttemptRevision\)/);
  assert.doesNotMatch(emailHandler, /new DesktopApiClient\(\{ \.\.\.config, apiKey: '' \}\)/);
});

test('login validation remains localized in English and Simplified Chinese', () => {
  assert.match(
    i18nSource,
    /'login\.invalidCredentials': 'Enter a valid work email and at least 6 password characters\.'/,
  );
  assert.match(
    i18nSource,
    /'login\.invalidCredentials': '请输入有效的工作邮箱，密码至少 6 个字符。'/,
  );
  assert.match(
    i18nSource,
    /'login\.restoreFailed': 'Saved sign-in could not be restored\. Sign in again\.'/,
  );
  assert.match(i18nSource, /'login\.restoreFailed': '无法恢复已保存的登录状态，请重新登录。'/);
  assert.match(
    i18nSource,
    /'login\.signOutPersistenceWarning':[\s\S]*'Signed out, but the revoked credential could not be removed from the encrypted application vault\.'/,
  );
  assert.match(
    i18nSource,
    /'login\.credentialStoreUnavailable':[\s\S]*'The encrypted application credential vault is unavailable\. Check desktop app-data access before switching accounts\.'/,
  );
  assert.match(
    i18nSource,
    /'login\.legacyLocalSessionCleared':\s*'Local workspace sign-in was removed\. Sign in with your cloud account to continue\.'/,
  );
  assert.match(
    i18nSource,
    /'login\.legacyLocalSessionCleared': '本地工作区登录已移除。请登录云端账号以继续。'/,
  );
  assert.doesNotMatch(i18nSource, /'login\.localWorkspace'/);
  assert.doesNotMatch(i18nSource, /'login\.modeLocal'/);
  assert.doesNotMatch(i18nSource, /'login\.switchToLocal'/);
  assert.match(i18nSource, /'login\.deviceTitle': 'Continue in your browser'/);
  assert.match(i18nSource, /'login\.deviceTitle': '在浏览器中继续'/);
  assert.match(i18nSource, /'login\.deviceWaiting': 'Waiting for approval…'/);
  assert.match(i18nSource, /'login\.deviceWaiting': '正在等待授权…'/);
  assert.match(i18nSource, /'runtime\.deviceAuthorizationUrl': 'Authorization portal URL'/);
  assert.match(i18nSource, /'runtime\.deviceAuthorizationUrl': '授权门户地址'/);
});

test('the workspace continue action starts cloud device authorization', () => {
  assert.match(loginSource, /resolveWorkspaceContinueLabelKey\(\)/);
  assert.match(loginSource, /resolveWorkspaceSsoAction\(\)/);
  assert.match(loginSource, /action\.kind === 'workspace_sso'/);
  assert.match(loginSource, /onWorkspaceSso\(trustedDevice\)/);
  assert.doesNotMatch(loginSource, /local_session|login\.localWorkspaceUnavailable/);
  assert.doesNotMatch(desktopAuthSource, /createLocalSession\(/);
  assert.doesNotMatch(loginSource, /t\('login\.workspaceSsoUnavailable'\)/);
});

test('workspace SSO shows one accessible device authorization checkpoint', () => {
  assert.match(loginSource, /workspaceSso: WorkspaceSsoPresentation \| null/);
  assert.match(loginSource, /role="dialog"/);
  assert.match(loginSource, /aria-modal="true"/);
  assert.match(loginSource, /workspaceSso\.userCode/);
  assert.match(loginSource, /onOpenWorkspaceSso/);
  assert.match(loginSource, /onCancelWorkspaceSso/);
  assert.doesNotMatch(loginSource, /t\('login\.switchToLocal'\)/);
  assert.match(loginSource, /'login\.deviceWaiting'/);
  assert.match(loginSource, /'login\.deviceExpiresCountdown'/);
  assert.match(loginSource, /'login\.deviceExpiredStatus'/);
  assert.match(loginSource, /aria-describedby="desktop-device-auth-description"/);
  assert.match(loginStyles, /\.desktop-device-auth-backdrop/);
  assert.match(loginStyles, /\.desktop-device-auth-dialog/);
});

test('workspace SSO polls by structured protocol state and is cancellable', () => {
  assert.match(desktopAuthSource, /createDeviceCode\(controller\.signal\)/);
  assert.match(desktopAuthSource, /pollDeviceToken\([\s\S]{0,100}deviceAuthorization\.device_code/);
  assert.match(desktopAuthSource, /classifyDeviceTokenError\(caught\)/);
  assert.match(appSource, /deviceAuthAttemptRef/);
  assert.match(appSource, /cancelWorkspaceSso/);
  assert.match(desktopAuthSource, /open_device_authorization_url/);
  assert.match(desktopAuthSource, /expectedUserCode/);
  assert.match(appSource, /openInFlight/);
  assert.match(desktopAuthSource, /window\.open\('about:blank', '_blank'\)/);
  assert.match(desktopAuthSource, /opened\.opener = null/);
  assert.match(desktopAuthSource, /opened\.location\.replace\(authorizationUrl\)/);
  assert.match(appSource, /WorkspaceSsoFlowError/);
  assert.match(desktopAuthSource, /keepExpiredPresentation/);
  assert.doesNotMatch(appSource, /localStorage[\s\S]*device_code/);

  assert.match(desktopAuthSource, /nativeAuthClient\.beginDeviceAuthorization/);
  assert.match(desktopAuthSource, /nativeAuthClient\.pollDeviceAuthorization/);
  assert.match(desktopAuthSource, /hydrateProjectedCloudSession\(authRevision\)/);
  assert.doesNotMatch(desktopAuthSource, /saveNativeTrustedSession/);
  assert.match(cloudAuthAuthoritySource, /#adoptToken/);
  assert.match(cloudAuthAuthoritySource, /saveTrustedSession/);
});

test('device grant cleanup covers cancellation, expiry, retry, supersession, unmount and approval races', () => {
  assert.match(desktopAuthSource, /let issuedDeviceCode = '';/);
  assert.match(
    desktopAuthSource,
    /const deviceAuthorization = await loginClient\.createDeviceCode\(controller\.signal\);\s*issuedDeviceCode = deviceAuthorization\.device_code;\s*if \(!deviceAuthAttemptIsCurrent/,
  );
  assert.match(
    desktopAuthSource,
    /const token = await loginClient\.pollDeviceToken\([\s\S]{0,160}?\);\s*issuedAccessToken = token\.access_token;\s*if \(!deviceAuthAttemptIsCurrent/,
  );
  assert.match(
    desktopAuthSource,
    /if \(issuedDeviceCode && !tokenAdopted\) \{\s*await cancelIssuedDeviceCodeBestEffort\(issuedDeviceCode, runtimeConfig\);\s*\}/,
  );
  assert.match(
    desktopAuthSource,
    /const cancelController = new AbortController\(\);[\s\S]{0,400}?cancelDeviceCode\(\s*deviceCode,\s*cancelController\.signal/,
  );
  assert.match(
    appSource,
    /useEffect\(\s*\(\) => \(\) => \{\s*deviceAuthAttemptRef\.current\?\.controller\.abort\(\);\s*deviceAuthAttemptRef\.current = null;/,
  );
  assert.match(
    desktopAuthSource,
    /const supersedeWorkspaceSsoAttempt = \(clearPresentation = true\) => \{\s*deviceAuthAttemptRef\.current\?\.controller\.abort\(\);\s*deviceAuthAttemptRef\.current = null;/,
  );
  assert.match(
    desktopAuthSource,
    /deviceError\?\.code === 'authorization_pending'[\s\S]{0,180}?continue;/,
  );
  assert.match(desktopAuthSource, /caught instanceof WorkspaceSsoFlowError && caught\.code === 'expired'/);
  assert.match(desktopAuthSource, /nativeSessionAdopted && !nativeFlowCompleted/);
  assert.match(desktopAuthSource, /nativeDeviceAttemptId && !nativeSessionAdopted/);
  assert.match(desktopAuthSource, /issuedDeviceCode && !tokenAdopted/);

  const attemptRefStart = appSource.indexOf('const deviceAuthAttemptRef = useRef');
  const attemptRefEnd = appSource.indexOf('const runInputRequestRef', attemptRefStart);
  const attemptRefSource = appSource.slice(attemptRefStart, attemptRefEnd);
  assert.doesNotMatch(attemptRefSource, /deviceCode|device_code/);
  assert.doesNotMatch(appSource, /(?:localStorage|sessionStorage)[\s\S]{0,160}?device_code/);
});

test('email login revokes failed tokens while retaining only the guarded password-change token', () => {
  const loginStart = desktopAuthSource.indexOf('const login = async (trustedDevice: boolean) =>');
  const loginEnd = desktopAuthSource.indexOf('const handleConfigChange', loginStart);
  const emailLoginSource = desktopAuthSource.slice(loginStart, loginEnd);
  assert.match(emailLoginSource, /let issuedAccessToken = '';/);
  assert.match(emailLoginSource, /issuedAccessToken = outcome\.access_token;/);
  assert.match(emailLoginSource, /let tokenAdopted = false;/);
  assert.match(emailLoginSource, /tokenAdopted = true;/);
  assert.match(emailLoginSource, /let passwordChangeTokenRetained = false;/);
  assert.match(emailLoginSource, /passwordChangeTokenRetained = true;/);
  assert.match(emailLoginSource, /pendingPasswordChangeRef\.current = \{/);
  assert.match(
    emailLoginSource,
    /finally \{\s*if \(issuedAccessToken && !tokenAdopted && !passwordChangeTokenRetained\) \{\s*await revokeUnadoptedDeviceToken/,
  );
});

test('authentication and workspace context failures are localized at their source', () => {
  const localizedKeys = [
    'runtime.activeTenantUnavailable',
    'runtime.activeProjectUnavailable',
    'login.authenticatedTenantUnavailable',
    'login.authoritativeProjectUnavailable',
    'login.authenticatedContextMismatch',
    'login.manualApiKeyRequiresValidation',
    'settings.selectedTenantUnavailable',
    'settings.selectedProjectUnavailable',
    'settings.contextResponseMismatch',
  ];
  const appAndAuthSource = appSource + desktopAuthSource;

  for (const key of localizedKeys) {
    assert.match(appAndAuthSource, new RegExp(`t\\('${key.replaceAll('.', '\\.')}'\\)`));
    assert.equal((i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length, 2);
  }

  assert.doesNotMatch(appSource, /settings\.authenticatedContextRequired/);

  assert.doesNotMatch(
    appSource,
    /The (?:active|authenticated|authoritative|local|selected|trusted|workspace|context)[^']+(?:tenant|project|runtime|workspace context|workspace)[^']*\./,
  );
  assert.doesNotMatch(appSource, /Manual API keys must be validated[^']+\./);
});

test('login geometry and primary action colors match the approved prototype', () => {
  assert.match(
    loginStyles,
    /grid-template-columns: minmax\(430px, 0\.78fr\) minmax\(560px, 1\.22fr\)/,
  );
  assert.match(loginStyles, /min-height: 720px/);
  assert.match(loginStyles, /color: var\(--desktop-text\)/);
  assert.doesNotMatch(loginStyles, /min-width: 1100px/);
  assert.match(loginStyles, /\.desktop-login-card \{[\s\S]*width: min\(430px, 100%\)/);
  assert.match(
    loginStyles,
    /\.desktop-login-submit \{[\s\S]*background: var\(--desktop-cyan-deep\);[\s\S]*border: 1px solid var\(--desktop-border-cyan-4\)/,
  );
  assert.match(
    loginStyles,
    /\.desktop-login-submit:hover \{[\s\S]*background: var\(--desktop-cyan-rich\)/,
  );
  assert.match(
    loginStyles,
    /@media \(max-height: 719px\) \{[\s\S]*\.desktop-login-screen \{[\s\S]*min-height: 0/,
  );
});

test('browser storage never receives a trusted session credential or recovery capability', () => {
  assert.doesNotMatch(appSource, /window\.localStorage/);
  assert.doesNotMatch(appSource, /trustedLocalSessionReference/);
  assert.doesNotMatch(appSource, /writeTrustedLocalSessionReference/);
  assert.doesNotMatch(appSource, /readTrustedLocalSessionReference/);
  assert.doesNotMatch(desktopAuthSource, /credential_kind: 'cloud_bearer'/);
  assert.match(cloudAuthAuthoritySource, /credential_kind: 'cloud_bearer'/);
  assert.doesNotMatch(appSource, /credential_kind: 'local_session_reference'/);
  assert.match(appSource, /purgeLegacyLoginModePreference\(/);
  assert.match(appSource, /purgeLegacyLocalLoginResidue\(/);
  assert.doesNotMatch(appSource, /loadNativeTrustedSession\(\)/);
  assert.match(
    appSource,
    /const projection = await hydrateProjectedCloudSession\(authAttemptRevision\)/,
  );
  assert.match(
    desktopAuthSource,
    /const projectionClient = desktopCloudSessionProjectionClient\(\)/,
  );
  assert.match(
    desktopAuthSource,
    /createProjectedCloudSessionState\(projection, configRef\.current\)/,
  );
  assert.match(appSource, /clearNativeTrustedSession\(\)/);
  assert.match(appSource, /settleTrustedSessionRestoreFailure\(/);
  assert.match(appSource, /'login\.restoreUnavailable' : 'login\.restoreFailed'/);
  assert.match(loginSource, /onRetrySavedSession/);
  assert.match(desktopAuthSource, /if \(outcome\.must_change_password\)/);
  assert.match(appSource, /authAttemptRevisionRef/);
  assert.match(appSource, /authAttemptRevisionRef\.current !== authAttemptRevision/);
  assert.match(appSource, /legacyLocalLoginNotice=\{legacyLocalLoginNotice\}/);
  assert.match(loginRuntimeSource, /agistack\.desktop\.login-mode/);
  assert.match(loginRuntimeSource, /purgeLegacyLoginModePreference/);
  assert.doesNotMatch(loginRuntimeSource, /JSON\.stringify\(\{ version: 1, mode \}\)/);
  assert.doesNotMatch(loginRuntimeSource, /tenantId: 'local'|projectId: 'local-project'/);
});
