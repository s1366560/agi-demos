import { useI18n } from '../i18n';
import {
  DesktopApiClient,
} from '../api/client';
import { desktopNativeCloudAuthClient } from '../api/nativeCloudAuthClient';
import {
  clearNativeTrustedSession,
  hasNativeTrustedSessionBroker,
} from '../api/trustedSession';
import {
  isSameDesktopRequestScope,
  resolveSignOutDisposition,
} from '../features/auth/authContextModel';
import {
  completeForcedPasswordChangeOutcome,
  passwordChangeGateAuthState,
} from '../features/auth/forcePasswordChangeModel';
import {
  runtimeConfigForLoginAvailability,
} from '../features/auth/loginRuntimeModel';
import {
  runtimeTransportIdentityChanged,
} from '../features/runtime/runtimeConfigModel';
import {
  DEFAULT_CONFIG,
  DesktopRuntimeConfig,
  LoginOutcome,
} from '../types';
import {
  formatLoginError,
} from '../utils/format';
import {
  emptyAuthState,
} from '../appShellTypes';
import type { DesktopAuthParams } from './useDesktopAuth';
import type { useCloudSessionAuth } from './useCloudSessionAuth';

type CloudSessionAuthApi = Pick<
  ReturnType<typeof useCloudSessionAuth>,
  | 'hydrateCloudSession'
  | 'hydrateProjectedCloudSession'
  | 'revokeUnadoptedDeviceToken'
  | 'supersedeWorkspaceSsoAttempt'
>;

export function useLocalCredentialAuth(
  params: DesktopAuthParams,
  cloudAuth: CloudSessionAuthApi,
) {
  const { t } = useI18n();
  const {
    hydrateCloudSession,
    hydrateProjectedCloudSession,
    revokeUnadoptedDeviceToken,
    supersedeWorkspaceSsoAttempt,
  } = cloudAuth;
  const {
    runsInNativeDesktop,
    config,
    auth,
    loginEmail,
    loginPassword,
    api,
    setAuth,
    setLoginModalOpen,
    setLoginEmail,
    setLoginPassword,
    setConnection,
    setError,
    setActiveSection,
    setSectionBackStack,
    setSectionForwardStack,
    setAgentConversationSession,
    setAgentTaskSignals,
    activeSectionRef,
    contextRevisionRef,
    configRef,
    localResumeAttemptRef,
    authAttemptRevisionRef,
    pendingPasswordChangeRef,
    commitRuntimeConfig,
    resetConversationTimeline,
    resetProjectScopedState,
    refreshRuntime,
    applySectionSideEffects,
  } = params;
  const login = async (trustedDevice: boolean) => {
    supersedeWorkspaceSsoAttempt();
    const username = loginEmail.trim();
    if (!username || !loginPassword) return;
    const runtimeConfig = runtimeConfigForLoginAvailability(configRef.current);

    const authAttemptRevision = ++authAttemptRevisionRef.current;
    localResumeAttemptRef.current = '';
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    let issuedAccessToken = '';
    let tokenAdopted = false;
    let passwordChangeTokenRetained = false;
    try {
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearNativeTrustedSession();
        } catch {
          // An uncleared record may belong to another identity. Fail closed before account switch.
          throw new Error(t('login.credentialStoreUnavailable'));
        }
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      }
      const nativeAuthClient =
        runsInNativeDesktop && runtimeConfig.mode === 'cloud'
          ? desktopNativeCloudAuthClient()
          : null;
      if (nativeAuthClient) {
        const result = await nativeAuthClient.loginWithPassword({
          apiBaseUrl: runtimeConfig.apiBaseUrl,
          username,
          password: loginPassword,
          trustedDevice,
        });
        if (authAttemptRevisionRef.current !== authAttemptRevision) {
          await nativeAuthClient.signOut().catch(() => undefined);
          return;
        }
        if (result.status === 'password_change_required') {
          pendingPasswordChangeRef.current = {
            outcome: {
              access_token: '',
              token_type: 'bearer',
              must_change_password: true,
            },
            runtimeConfig,
            trustedDevice,
            authRevision: authAttemptRevision,
          };
          passwordChangeTokenRetained = true;
          setLoginPassword('');
          setAuth(passwordChangeGateAuthState(false, null));
          setConnection('idle');
          setError(null);
          return;
        }
        const projection = await hydrateProjectedCloudSession(authAttemptRevision);
        if (!projection) {
          await nativeAuthClient.signOut().catch(() => undefined);
          return;
        }
        tokenAdopted = true;
        return;
      }

      const loginClient = new DesktopApiClient({ ...runtimeConfig, apiKey: '' });
      const outcome = await loginClient.login(username, loginPassword);
      issuedAccessToken = outcome.access_token;
      if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      if (outcome.must_change_password) {
        pendingPasswordChangeRef.current = {
          outcome,
          runtimeConfig,
          trustedDevice,
          authRevision: authAttemptRevision,
        };
        passwordChangeTokenRetained = true;
        setLoginPassword('');
        setAuth(passwordChangeGateAuthState(false, null));
        setConnection('idle');
        setError(null);
        return;
      }
      const hydrated = await hydrateCloudSession(outcome, runtimeConfig, authAttemptRevision);
      if (!hydrated) return;
      tokenAdopted = true;
    } catch (caught) {
      if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearNativeTrustedSession();
        } catch {
          // Preserve the original authentication failure without exposing credential-store detail.
        }
      }
      const message = formatLoginError(caught, runtimeConfig.apiBaseUrl);
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
    } finally {
      if (issuedAccessToken && !tokenAdopted && !passwordChangeTokenRetained) {
        await revokeUnadoptedDeviceToken(issuedAccessToken, runtimeConfig);
      }
    }
  };

  const submitForcedPasswordChange = async (
    currentPassword: string,
    newPassword: string,
  ) => {
    const pending = pendingPasswordChangeRef.current;
    if (
      !pending ||
      (auth.status !== 'password_change_required' &&
        auth.status !== 'changing_password') ||
      authAttemptRevisionRef.current !== pending.authRevision
    ) {
      return;
    }

    setAuth(passwordChangeGateAuthState(true, null));
    setConnection('loading');
    setError(null);
    let passwordChanged = false;
    let tokenAdopted = false;
    try {
      const nativeAuthClient =
        runsInNativeDesktop && pending.runtimeConfig.mode === 'cloud'
          ? desktopNativeCloudAuthClient()
          : null;
      if (nativeAuthClient) {
        await nativeAuthClient.forceChangePassword({ currentPassword, newPassword });
        passwordChanged = true;
        if (authAttemptRevisionRef.current !== pending.authRevision) {
          await nativeAuthClient.signOut().catch(() => undefined);
          return;
        }
        const projection = await hydrateProjectedCloudSession(pending.authRevision);
        if (!projection) {
          await nativeAuthClient.signOut().catch(() => undefined);
          return;
        }
        tokenAdopted = true;
        pendingPasswordChangeRef.current = null;
        return;
      }

      const passwordClient = new DesktopApiClient({
        ...pending.runtimeConfig,
        apiKey: pending.outcome.access_token,
      });
      await passwordClient.forceChangePassword(currentPassword, newPassword);
      passwordChanged = true;
      if (authAttemptRevisionRef.current !== pending.authRevision) {
        await revokeUnadoptedDeviceToken(
          pending.outcome.access_token,
          pending.runtimeConfig,
        );
        return;
      }

      const hydrated = await hydrateCloudSession(
        completeForcedPasswordChangeOutcome(pending.outcome),
        pending.runtimeConfig,
        pending.authRevision,
      );
      if (!hydrated) {
        await revokeUnadoptedDeviceToken(
          pending.outcome.access_token,
          pending.runtimeConfig,
        );
        return;
      }
      tokenAdopted = true;
      pendingPasswordChangeRef.current = null;
    } catch (caught) {
      if (authAttemptRevisionRef.current !== pending.authRevision) return;
      if (passwordChanged) {
        pendingPasswordChangeRef.current = null;
        if (!tokenAdopted) {
          await revokeUnadoptedDeviceToken(
            pending.outcome.access_token,
            pending.runtimeConfig,
          );
        }
        const message = t('forcePassword.changedSignInFailed');
        setAuth({ ...emptyAuthState, error: message });
        setConnection('error');
        setError(message);
        return;
      }
      const message = formatLoginError(
        caught,
        pending.runtimeConfig.apiBaseUrl,
      );
      setAuth(passwordChangeGateAuthState(false, message));
      setConnection('idle');
      setError(null);
    }
  };

  const cancelForcedPasswordChange = () => {
    const pending = pendingPasswordChangeRef.current;
    if (!pending) return;
    authAttemptRevisionRef.current += 1;
    pendingPasswordChangeRef.current = null;
    setLoginPassword('');
    setAuth(emptyAuthState);
    setConnection('idle');
    setError(null);
    const nativeAuthClient =
      runsInNativeDesktop && pending.runtimeConfig.mode === 'cloud'
        ? desktopNativeCloudAuthClient()
        : null;
    if (nativeAuthClient) {
      void nativeAuthClient.signOut().catch(() => undefined);
    } else {
      void revokeUnadoptedDeviceToken(
        pending.outcome.access_token,
        pending.runtimeConfig,
      );
    }
  };

  const handleConfigChange = (nextConfig: DesktopRuntimeConfig) => {
    const previousConfig = configRef.current;
    const transportIdentityChanged = runtimeTransportIdentityChanged(
      previousConfig,
      nextConfig,
    );
    const transportSafeConfig = transportIdentityChanged
      ? { ...nextConfig, apiKey: '', localApiToken: '' }
      : nextConfig;
    const resolvedConfig = transportSafeConfig;
    const requestScopeChanged = !isSameDesktopRequestScope(
      previousConfig,
      resolvedConfig,
    );
    if (transportIdentityChanged) {
      supersedeWorkspaceSsoAttempt();
      const authAttemptRevision = ++authAttemptRevisionRef.current;
      localResumeAttemptRef.current = '';
      setAuth(emptyAuthState);
      if (hasNativeTrustedSessionBroker()) {
        void clearNativeTrustedSession().catch(() => {
          if (authAttemptRevisionRef.current === authAttemptRevision) {
            setError(t('login.persistenceUnavailable'));
          }
        });
      }
    }
    commitRuntimeConfig(resolvedConfig);
    if (requestScopeChanged) {
      resetProjectScopedState();
      return;
    }
    setConnection('idle');
    setAgentConversationSession(null);
    resetConversationTimeline();
    setAgentTaskSignals([]);
  };

  const useApiKeyManually = () => {
    setLoginModalOpen(false);
    setAuth((current) => ({
      ...current,
      error: t('login.manualApiKeyRequiresValidation'),
    }));
  };

  const logout = async () => {
    supersedeWorkspaceSsoAttempt();
    const authAttemptRevision = ++authAttemptRevisionRef.current;
    localResumeAttemptRef.current = '';
    const authenticatedClient = api;
    const nativeCloudAuthClient =
      runsInNativeDesktop && config.mode === 'cloud'
        ? desktopNativeCloudAuthClient()
        : null;
    const shouldRevoke = nativeCloudAuthClient !== null || Boolean(config.apiKey.trim());
    const hasCredentialBroker = hasNativeTrustedSessionBroker();
    const nativeSignOut = nativeCloudAuthClient?.signOut();
    const [credentialRevoked, persistedCredentialCleared] = await Promise.all([
      shouldRevoke
        ? (nativeSignOut ?? authenticatedClient.signOut())
            .then((outcome) => outcome.success === true)
            .catch(() => false)
        : Promise.resolve(false),
      nativeSignOut
        ? nativeSignOut.then(() => true).catch(() => false)
        : hasCredentialBroker
          ? clearNativeTrustedSession()
              .then(() => true)
              .catch(() => false)
        : Promise.resolve(true),
    ]);
    if (authAttemptRevisionRef.current !== authAttemptRevision) return;
    const signOutDisposition = resolveSignOutDisposition(
      hasCredentialBroker,
      persistedCredentialCleared,
      credentialRevoked,
    );
    if (signOutDisposition === 'blocked') {
      setError(t('login.signOutPersistenceFailed'));
      return;
    }
    const persistenceWarning =
      signOutDisposition === 'complete_with_persistence_warning'
        ? t('login.signOutPersistenceWarning')
        : null;
    localResumeAttemptRef.current = `${config.mode}|${config.apiBaseUrl}|${config.localApiToken}`;
    contextRevisionRef.current += 1;
    setAuth(
      persistenceWarning
        ? { ...emptyAuthState, error: persistenceWarning }
        : emptyAuthState,
    );
    setLoginModalOpen(false);
    commitRuntimeConfig({
      ...DEFAULT_CONFIG,
      apiBaseUrl: config.apiBaseUrl,
      deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
      localApiToken: config.localApiToken,
      mode: config.mode,
      workspaceRoot: config.workspaceRoot,
    });
    resetProjectScopedState();
    setSectionBackStack([]);
    setSectionForwardStack([]);
    activeSectionRef.current = 'workspace';
    setActiveSection('workspace');
    setError(persistenceWarning);
  };
  return {
    cancelForcedPasswordChange,
    handleConfigChange,
    login,
    logout,
    submitForcedPasswordChange,
    useApiKeyManually,
  };
}
