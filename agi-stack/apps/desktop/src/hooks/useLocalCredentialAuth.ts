import { useI18n } from '../i18n';
import {
  DesktopApiClient,
} from '../api/client';
import {
  clearLocalTrustedSession,
  clearNativeTrustedSession,
  hasNativeTrustedSessionBroker,
  saveLocalTrustedSession,
  saveNativeTrustedSession,
  type NativeTrustedSession,
} from '../api/trustedSession';
import {
  findWorkspaceProject,
  isSameDesktopRequestScope,
  resolveSignOutDisposition,
} from '../features/auth/authContextModel';
import {
  completeForcedPasswordChangeOutcome,
  passwordChangeGateAuthState,
} from '../features/auth/forcePasswordChangeModel';
import {
  runtimeConfigForLoginAvailability,
  runtimeConfigForLoginMode,
  writeLoginModePreference,
} from '../features/auth/loginRuntimeModel';
import {
  runtimeTransportIdentityChanged,
} from '../features/runtime/runtimeConfigModel';
import {
  DEFAULT_CONFIG,
  DesktopRuntimeConfig,
  LoginOutcome,
  RuntimeMode,
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
    localRuntimeAuthorityReady,
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
    const runtimeConfig = runtimeConfigForLoginAvailability(
      configRef.current,
      runsInNativeDesktop,
    );

    const authAttemptRevision = ++authAttemptRevisionRef.current;
    localResumeAttemptRef.current = '';
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    let persistenceWarning: string | null = null;
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
      if (trustedDevice && hasNativeTrustedSessionBroker()) {
        const trustedSession: NativeTrustedSession = {
          version: 1,
          api_base_url: runtimeConfig.apiBaseUrl,
          runtime_mode: 'cloud',
          credential_kind: 'cloud_bearer',
          credential: outcome.access_token,
          expires_at: outcome.session?.expires_at ?? null,
        };
        try {
          await saveNativeTrustedSession(trustedSession);
        } catch {
          persistenceWarning = t('login.persistenceUnavailable');
        }
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      }
      const hydrated = await hydrateCloudSession(outcome, runtimeConfig, authAttemptRevision);
      if (!hydrated) return;
      tokenAdopted = true;
      if (persistenceWarning) setError(persistenceWarning);
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
    let persistedNativeSession = false;
    try {
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

      let persistenceWarning: string | null = null;
      if (pending.trustedDevice && hasNativeTrustedSessionBroker()) {
        try {
          await saveNativeTrustedSession({
            version: 1,
            api_base_url: pending.runtimeConfig.apiBaseUrl,
            runtime_mode: 'cloud',
            credential_kind: 'cloud_bearer',
            credential: pending.outcome.access_token,
            expires_at: pending.outcome.session?.expires_at ?? null,
          });
          persistedNativeSession = true;
        } catch {
          persistenceWarning = t('login.persistenceUnavailable');
        }
        if (authAttemptRevisionRef.current !== pending.authRevision) {
          if (persistedNativeSession) {
            await clearNativeTrustedSession().catch(() => undefined);
          }
          await revokeUnadoptedDeviceToken(
            pending.outcome.access_token,
            pending.runtimeConfig,
          );
          return;
        }
      }

      const hydrated = await hydrateCloudSession(
        completeForcedPasswordChangeOutcome(pending.outcome),
        pending.runtimeConfig,
        pending.authRevision,
      );
      if (!hydrated) {
        if (persistedNativeSession) {
          await clearNativeTrustedSession().catch(() => undefined);
        }
        await revokeUnadoptedDeviceToken(
          pending.outcome.access_token,
          pending.runtimeConfig,
        );
        return;
      }
      tokenAdopted = true;
      pendingPasswordChangeRef.current = null;
      if (persistenceWarning) setError(persistenceWarning);
    } catch (caught) {
      if (authAttemptRevisionRef.current !== pending.authRevision) return;
      if (passwordChanged) {
        pendingPasswordChangeRef.current = null;
        if (persistedNativeSession) {
          await clearNativeTrustedSession().catch(() => undefined);
        }
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
    void revokeUnadoptedDeviceToken(
      pending.outcome.access_token,
      pending.runtimeConfig,
    );
  };

  const hydrateLocalSession = async (
    outcome: LoginOutcome,
    runtimeConfig: DesktopRuntimeConfig,
    authAttemptRevision: number,
  ): Promise<boolean> => {
    if (!outcome.context) {
      throw new Error(t('login.localContextMissing'));
    }
    const localContext = outcome.context;
    const tokenConfig = {
      ...runtimeConfig,
      apiKey: outcome.access_token,
      tenantId: localContext.tenant_id,
      projectId: localContext.project_id,
      workspaceId: '',
    };
    const identityClient = new DesktopApiClient(tokenConfig);
    const [user, tenants, projects] = await Promise.all([
      identityClient.currentUser(),
      identityClient.listTenants(),
      identityClient.listProjects(localContext.tenant_id),
    ]);
    if (authAttemptRevisionRef.current !== authAttemptRevision) return false;
    if (!tenants.some((tenant) => tenant.id === localContext.tenant_id)) {
      throw new Error(t('login.localTenantUnavailable'));
    }
    const scopedProjects = projects.filter(
      (project) => project.tenant_id === localContext.tenant_id,
    );
    const selectedProject = findWorkspaceProject(
      scopedProjects,
      localContext.tenant_id,
      localContext.project_id,
    );
    if (!selectedProject) {
      throw new Error(t('login.localProjectUnavailable'));
    }

    contextRevisionRef.current = localContext.revision;
    resetProjectScopedState();
    commitRuntimeConfig(tokenConfig);
    setAuth({
      status: 'signed_in',
      credentialKind: 'local_session',
      session: outcome.session ?? null,
      context: localContext,
      user,
      tenants,
      projects: scopedProjects,
      mustChangePassword: false,
      error: null,
    });
    await refreshRuntime(tokenConfig, [selectedProject]);
    return authAttemptRevisionRef.current === authAttemptRevision;
  };

  const loginLocalSession = async (trustedDevice: boolean) => {
    supersedeWorkspaceSsoAttempt();
    if (!localRuntimeAuthorityReady) {
      setAuth((current) => ({
        ...current,
        error: t('login.localRuntimeNotReady'),
      }));
      return;
    }

    const authAttemptRevision = ++authAttemptRevisionRef.current;
    localResumeAttemptRef.current = '';
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    let persistenceWarning: string | null = null;
    try {
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearLocalTrustedSession();
        } catch {
          // An uncleared local reference may belong to another local session. Fail closed.
          throw new Error(t('login.credentialStoreUnavailable'));
        }
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      }
      const bootstrapClient = new DesktopApiClient({ ...config, apiKey: '' });
      const outcome = await bootstrapClient.createLocalSession(trustedDevice);
      if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      const sessionId = outcome.session?.session_id?.trim();
      if (trustedDevice && hasNativeTrustedSessionBroker() && sessionId) {
        const trustedSession: NativeTrustedSession = {
          version: 1,
          api_base_url: config.apiBaseUrl,
          runtime_mode: 'local',
          credential_kind: 'local_session_reference',
          credential: sessionId,
          expires_at: outcome.session?.expires_at ?? null,
        };
        try {
          await saveLocalTrustedSession(trustedSession);
        } catch {
          persistenceWarning = t('login.persistenceUnavailable');
        }
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      }
      const hydrated = await hydrateLocalSession(
        outcome,
        config,
        authAttemptRevision,
      );
      if (!hydrated) return;
      applySectionSideEffects('workspace');
      if (persistenceWarning) setError(persistenceWarning);
    } catch (caught) {
      if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearLocalTrustedSession();
        } catch {
          // Preserve the original authentication failure without exposing credential-store detail.
        }
      }
      const message = formatLoginError(caught, config.apiBaseUrl);
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
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
    const resolvedConfig =
      transportSafeConfig.mode === 'local'
        ? {
            ...transportSafeConfig,
            tenantId: transportSafeConfig.tenantId.trim() || 'local',
            projectId: transportSafeConfig.projectId.trim() || 'local-project',
          }
        : transportSafeConfig;
    const requestScopeChanged = !isSameDesktopRequestScope(
      previousConfig,
      resolvedConfig,
    );
    if (previousConfig.mode !== resolvedConfig.mode) {
      writeLoginModePreference(resolvedConfig.mode);
    }
    if (transportIdentityChanged) {
      supersedeWorkspaceSsoAttempt();
      const authAttemptRevision = ++authAttemptRevisionRef.current;
      localResumeAttemptRef.current = '';
      setAuth(emptyAuthState);
      if (hasNativeTrustedSessionBroker()) {
        const clearTrustedSession =
          previousConfig.mode === 'local'
            ? clearLocalTrustedSession
            : clearNativeTrustedSession;
        void clearTrustedSession().catch(() => {
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

  const changeLoginMode = (mode: RuntimeMode) => {
    const nextMode: RuntimeMode = mode;
    if (nextMode === configRef.current.mode) return;
    setLoginEmail('');
    setLoginPassword('');
    handleConfigChange(runtimeConfigForLoginMode(configRef.current, nextMode));
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
    const shouldRevoke = Boolean(config.apiKey.trim());
    const hasCredentialBroker = hasNativeTrustedSessionBroker();
    const [credentialRevoked, persistedCredentialCleared] = await Promise.all([
      shouldRevoke
        ? authenticatedClient
            .signOut()
            .then((outcome) => outcome.success === true)
            .catch(() => false)
        : Promise.resolve(false),
      hasCredentialBroker
        ? (config.mode === 'local'
            ? clearLocalTrustedSession()
            : clearNativeTrustedSession()
          )
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
    changeLoginMode,
    handleConfigChange,
    hydrateLocalSession,
    login,
    loginLocalSession,
    logout,
    submitForcedPasswordChange,
    useApiKeyManually,
  };
}
