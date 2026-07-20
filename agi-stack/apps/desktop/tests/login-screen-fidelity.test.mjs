import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const loginSource = readFileSync(
  new URL('../src/features/auth/LoginScreen.tsx', import.meta.url),
  'utf8'
);
const loginStyles = readFileSync(
  new URL('../src/features/auth/LoginScreen.css', import.meta.url),
  'utf8'
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

test('approved email path owns the trusted-device choice and inline alert', () => {
  assert.match(loginSource, /onEmailLogin: \(trustedDevice: boolean\) => void/);
  assert.match(loginSource, /onEmailLogin\(trustedDevice\)/);
  assert.match(loginSource, /validateLoginCredentials\(email, password\)/);
  assert.match(loginSource, /<form[\s\S]*noValidate/);
  assert.match(loginSource, /role="alert"/);
  assert.match(loginSource, /t\('login\.invalidCredentials'\)/);
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
  assert.match(i18nSource, /'login\.localWorkspace': 'Continue with local workspace'/);
  assert.match(i18nSource, /'login\.localWorkspace': '继续使用本地工作区'/);
  assert.match(
    i18nSource,
    /'login\.localWorkspaceUnavailable': 'The trusted local workspace is not ready yet\.'/,
  );
  assert.match(i18nSource, /'login\.localWorkspaceUnavailable': '受信任的本地工作区尚未就绪。'/);
  assert.match(i18nSource, /'login\.deviceTitle': 'Continue in your browser'/);
  assert.match(i18nSource, /'login\.deviceTitle': '在浏览器中继续'/);
  assert.match(i18nSource, /'login\.deviceWaiting': 'Waiting for approval…'/);
  assert.match(i18nSource, /'login\.deviceWaiting': '正在等待授权…'/);
});

test('the workspace continue action exposes local and cloud authority without a fake success path', () => {
  assert.match(loginSource, /resolveWorkspaceContinueLabelKey\(mode\)/);
  assert.match(
    loginSource,
    /resolveWorkspaceSsoAction\(mode, localReady, trustedDevice\)/,
  );
  assert.match(loginSource, /onLocalSession\(action\.trustedDevice\)/);
  assert.match(
    appSource,
    /onLocalSession=\{\(trustedDevice\) => void loginLocalSession\(trustedDevice\)\}/,
  );
  assert.match(appSource, /createLocalSession\(trustedDevice\)/);
  assert.match(
    appSource,
    /if \(trustedDevice && hasNativeTrustedSessionBroker\(\) && sessionId\)/,
  );
  assert.match(loginSource, /action\.kind === 'workspace_sso'/);
  assert.match(loginSource, /t\('login\.localWorkspaceUnavailable'\)/);
  assert.match(loginSource, /onWorkspaceSso\(trustedDevice\)/);
  assert.doesNotMatch(loginSource, /t\('login\.workspaceSsoUnavailable'\)/);
});

test('workspace SSO shows one accessible device authorization checkpoint', () => {
  assert.match(loginSource, /workspaceSso: WorkspaceSsoPresentation \| null/);
  assert.match(loginSource, /role="dialog"/);
  assert.match(loginSource, /aria-modal="true"/);
  assert.match(loginSource, /workspaceSso\.userCode/);
  assert.match(loginSource, /onOpenWorkspaceSso/);
  assert.match(loginSource, /onCancelWorkspaceSso/);
  assert.match(loginSource, /'login\.deviceWaiting'/);
  assert.match(loginSource, /'login\.deviceExpiresCountdown'/);
  assert.match(loginSource, /'login\.deviceExpiredStatus'/);
  assert.match(loginSource, /aria-describedby="desktop-device-auth-description"/);
  assert.match(loginStyles, /\.desktop-device-auth-backdrop/);
  assert.match(loginStyles, /\.desktop-device-auth-dialog/);
});

test('workspace SSO polls by structured protocol state and is cancellable', () => {
  assert.match(appSource, /createDeviceCode\(controller\.signal\)/);
  assert.match(appSource, /pollDeviceToken\([\s\S]{0,100}deviceAuthorization\.device_code/);
  assert.match(appSource, /classifyDeviceTokenError\(caught\)/);
  assert.match(appSource, /deviceAuthAttemptRef/);
  assert.match(appSource, /cancelWorkspaceSso/);
  assert.match(appSource, /open_device_authorization_url/);
  assert.match(appSource, /expectedUserCode/);
  assert.match(appSource, /openInFlight/);
  assert.match(appSource, /window\.open\('about:blank', '_blank'\)/);
  assert.match(appSource, /opened\.opener = null/);
  assert.match(appSource, /opened\.location\.replace\(authorizationUrl\)/);
  assert.match(appSource, /WorkspaceSsoFlowError/);
  assert.match(appSource, /keepExpiredPresentation/);
  assert.doesNotMatch(appSource, /localStorage[\s\S]*device_code/);

  const nativeSave = appSource.indexOf('await saveNativeTrustedSession');
  const staleAttemptCheck = appSource.indexOf(
    'if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller))',
    nativeSave,
  );
  const adoption = appSource.indexOf('tokenAdopted = true', nativeSave);
  assert.ok(nativeSave >= 0 && staleAttemptCheck > nativeSave && adoption > staleAttemptCheck);
});

test('device grant cleanup covers cancellation, expiry, retry, supersession, unmount and approval races', () => {
  assert.match(appSource, /let issuedDeviceCode = '';/);
  assert.match(
    appSource,
    /const deviceAuthorization = await loginClient\.createDeviceCode\(controller\.signal\);\s*issuedDeviceCode = deviceAuthorization\.device_code;\s*if \(!deviceAuthAttemptIsCurrent/,
  );
  assert.match(
    appSource,
    /const token = await loginClient\.pollDeviceToken\([\s\S]{0,160}?\);\s*issuedAccessToken = token\.access_token;\s*if \(!deviceAuthAttemptIsCurrent/,
  );
  assert.match(
    appSource,
    /if \(issuedDeviceCode && !tokenAdopted\) \{\s*await cancelIssuedDeviceCodeBestEffort\(issuedDeviceCode, runtimeConfig\);\s*\}/,
  );
  assert.match(
    appSource,
    /const cancelController = new AbortController\(\);[\s\S]{0,400}?cancelDeviceCode\(\s*deviceCode,\s*cancelController\.signal/,
  );
  assert.match(
    appSource,
    /useEffect\(\s*\(\) => \(\) => \{\s*deviceAuthAttemptRef\.current\?\.controller\.abort\(\);\s*deviceAuthAttemptRef\.current = null;/,
  );
  assert.match(
    appSource,
    /const supersedeWorkspaceSsoAttempt = \(clearPresentation = true\) => \{\s*deviceAuthAttemptRef\.current\?\.controller\.abort\(\);\s*deviceAuthAttemptRef\.current = null;/,
  );
  assert.match(
    appSource,
    /deviceError\?\.code === 'authorization_pending'[\s\S]{0,180}?continue;/,
  );
  assert.match(
    appSource,
    /caught instanceof WorkspaceSsoFlowError && caught\.code === 'expired'[\s\S]{0,500}?return;[\s\S]{0,900}?issuedDeviceCode && !tokenAdopted/,
  );

  const attemptRefStart = appSource.indexOf('const deviceAuthAttemptRef = useRef');
  const attemptRefEnd = appSource.indexOf('const runInputRequestRef', attemptRefStart);
  const attemptRefSource = appSource.slice(attemptRefStart, attemptRefEnd);
  assert.doesNotMatch(attemptRefSource, /deviceCode|device_code/);
  assert.doesNotMatch(appSource, /(?:localStorage|sessionStorage)[\s\S]{0,160}?device_code/);
});

test('authentication and workspace context failures are localized at their source', () => {
  const localizedKeys = [
    'runtime.activeTenantUnavailable',
    'runtime.activeProjectUnavailable',
    'login.authenticatedTenantUnavailable',
    'login.authoritativeProjectUnavailable',
    'login.authenticatedContextMismatch',
    'login.localContextMissing',
    'login.localTenantUnavailable',
    'login.localProjectUnavailable',
    'login.localRuntimeNotReady',
    'login.manualApiKeyRequiresValidation',
    'settings.selectedTenantUnavailable',
    'settings.selectedProjectUnavailable',
    'settings.contextResponseMismatch',
  ];

  for (const key of localizedKeys) {
    assert.match(appSource, new RegExp(`t\\('${key.replaceAll('.', '\\.')}'\\)`));
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
  assert.match(loginStyles, /color: #e7edf6/);
  assert.doesNotMatch(loginStyles, /min-width: 1100px/);
  assert.match(loginStyles, /\.desktop-login-card \{[\s\S]*width: min\(430px, 100%\)/);
  assert.match(
    loginStyles,
    /\.desktop-login-submit \{[\s\S]*background: #146f87;[\s\S]*border: 1px solid #2b8ea7/,
  );
  assert.match(
    loginStyles,
    /\.desktop-login-submit:hover \{[\s\S]*background: #177c96/,
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
  assert.match(appSource, /credential_kind: 'cloud_bearer'/);
  assert.match(appSource, /credential_kind: 'local_session_reference'/);
  assert.match(appSource, /loadNativeTrustedSession\(\)/);
  assert.match(appSource, /clearNativeTrustedSession\(\)/);
  assert.match(appSource, /const message = t\('login\.restoreFailed'\)/);
  assert.match(appSource, /if \(outcome\.must_change_password\)/);
  assert.match(appSource, /authAttemptRevisionRef/);
  assert.match(appSource, /authAttemptRevisionRef\.current !== authAttemptRevision/);
  assert.match(appSource, /localReady=\{localRuntimeAuthorityReady\}/);
});
