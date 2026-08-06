import { useI18n } from '../i18n';
import {
  classifyDeviceTokenError,
  DesktopApiClient,
  isWorkspaceContextUnavailableError,
} from '../api/client';
import {
  clearNativeTrustedSession,
  hasNativeTrustedSessionBroker,
  saveNativeTrustedSession,
} from '../api/trustedSession';
import {
  findWorkspaceProject,
  workspaceContextMatchesSelection,
} from '../features/auth/authContextModel';
import {
  normalizeDeviceAuthorizationInterval,
  resolveDeviceAuthorizationUrl,
} from '../features/auth/loginScreenModel';
import {
  runtimeConfigForLoginAvailability,
} from '../features/auth/loginRuntimeModel';
import {
  DesktopRuntimeConfig,
  LoginOutcome,
} from '../types';
import {
  waitForAbortableDelay,
} from '../utils/format';
import {
  WorkspaceSsoFlowError,
  emptyAuthState,
  emptyDataset,
} from '../appShellTypes';
import type { DesktopAuthParams } from './useDesktopAuth';

export function useCloudSessionAuth(params: DesktopAuthParams) {
  const { t } = useI18n();
  const {
    runsInNativeDesktop,
    workspaceSso,
    setAuth,
    setLoginPassword,
    setWorkspaceSso,
    setDataset,
    setConnection,
    setError,
    setLastSync,
    setSettingsInitialSection,
    setSettingsWindowOpen,
    contextRevisionRef,
    configRef,
    authAttemptRevisionRef,
    deviceAuthAttemptIdRef,
    deviceAuthAttemptRef,
    commitRuntimeConfig,
    resetProjectScopedState,
    refreshRuntime,
    applySectionSideEffects,
  } = params;
  const hydrateCloudSession = async (
    outcome: LoginOutcome,
    runtimeConfig: DesktopRuntimeConfig,
    authAttemptRevision: number,
  ): Promise<boolean> => {
    const tokenConfig = {
      ...runtimeConfig,
      apiKey: outcome.access_token,
      workspaceId: '',
    };
    const identityClient = new DesktopApiClient(tokenConfig);
    const [user, tenants, authoritativeContextResponse] = await Promise.all([
      identityClient.currentUser(),
      identityClient.listTenants(),
      identityClient.getWorkspaceContext().catch((caught) => {
        if (isWorkspaceContextUnavailableError(caught)) return null;
        throw caught;
      }),
    ]);
    if (authAttemptRevisionRef.current !== authAttemptRevision) return false;
    if (!authoritativeContextResponse) {
      const nextConfig = {
        ...tokenConfig,
        tenantId: '',
        projectId: '',
        workspaceId: '',
      };
      contextRevisionRef.current = 0;
      resetProjectScopedState();
      commitRuntimeConfig(nextConfig);
      setAuth({
        status: 'signed_in',
        credentialKind: 'cloud_session',
        session: outcome.session ?? null,
        context: null,
        user,
        tenants,
        projects: [],
        mustChangePassword: outcome.must_change_password,
        error: null,
      });
      setLoginPassword('');
      setDataset(emptyDataset);
      setConnection('idle');
      setLastSync(
        new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
      );
      applySectionSideEffects('workspace');
      setSettingsInitialSection('workspace');
      setSettingsWindowOpen(true);
      return true;
    }
    const authoritativeContext = authoritativeContextResponse.context;
    const tenantId = authoritativeContext.tenant_id;
    const projectClient = new DesktopApiClient({ ...tokenConfig, tenantId });
    const projects = tenantId ? await projectClient.listProjects(tenantId) : [];
    if (authAttemptRevisionRef.current !== authAttemptRevision) return false;
    if (tenantId && !tenants.some((tenant) => tenant.id === tenantId)) {
      throw new Error(t('login.authenticatedTenantUnavailable'));
    }
    const scopedProjects = projects.filter((project) => project.tenant_id === tenantId);
    const preferredProjectId = authoritativeContext.project_id;
    const preferredProject = findWorkspaceProject(
      scopedProjects,
      tenantId,
      preferredProjectId,
    );
    const projectId = preferredProject?.id ?? '';
    if (
      !workspaceContextMatchesSelection(
        authoritativeContext,
        tenantId,
        projectId,
      )
    ) {
      throw new Error(t('login.authoritativeProjectUnavailable'));
    }
    const context = authoritativeContext;
    if (!workspaceContextMatchesSelection(context, tenantId, projectId)) {
      throw new Error(t('login.authenticatedContextMismatch'));
    }
    const nextConfig = { ...tokenConfig, tenantId, projectId, workspaceId: '' };

    contextRevisionRef.current = context.revision;
    resetProjectScopedState();
    commitRuntimeConfig(nextConfig);
    setAuth({
      status: 'signed_in',
      credentialKind: 'cloud_session',
      session: outcome.session ?? null,
      context,
      user,
      tenants,
      projects: scopedProjects,
      mustChangePassword: outcome.must_change_password,
      error: null,
    });
    setLoginPassword('');

    if (projectId) {
      await refreshRuntime(nextConfig, scopedProjects);
      if (authAttemptRevisionRef.current !== authAttemptRevision) return false;
      applySectionSideEffects('workspace');
    } else {
      setDataset(emptyDataset);
      setConnection('idle');
      setLastSync(
        new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
      );
      applySectionSideEffects('workspace');
      setSettingsInitialSection('workspace');
      setSettingsWindowOpen(true);
    }
    return true;
  };

  const deviceAuthAttemptIsCurrent = (
    attemptId: number,
    authRevision: number,
    controller: AbortController,
  ): boolean => {
    const current = deviceAuthAttemptRef.current;
    return Boolean(
      current?.attemptId === attemptId &&
      current.authRevision === authRevision &&
      authAttemptRevisionRef.current === authRevision &&
      !controller.signal.aborted,
    );
  };

  const supersedeWorkspaceSsoAttempt = (clearPresentation = true) => {
    deviceAuthAttemptRef.current?.controller.abort();
    deviceAuthAttemptRef.current = null;
    if (clearPresentation) setWorkspaceSso(null);
  };

  const revokeUnadoptedDeviceToken = async (
    accessToken: string,
    runtimeConfig: DesktopRuntimeConfig,
  ): Promise<void> => {
    if (!accessToken) return;
    try {
      await new DesktopApiClient({
        ...runtimeConfig,
        apiKey: accessToken,
      }).signOut();
    } catch {
      // Best effort only. Device-grant cancellation below independently retries revocation.
    }
  };

  const cancelIssuedDeviceCodeBestEffort = async (
    deviceCode: string,
    runtimeConfig: DesktopRuntimeConfig,
  ): Promise<void> => {
    if (!deviceCode) return;
    const cancelController = new AbortController();
    const timeoutId = window.setTimeout(() => cancelController.abort(), 3_000);
    try {
      const cancelClient = new DesktopApiClient({
        ...runtimeConfig,
        apiKey: '',
      });
      await cancelClient.cancelDeviceCode(deviceCode, cancelController.signal);
    } catch {
      // Best effort only. Pending grants expire, and an issued bearer is revoked separately above.
    } finally {
      window.clearTimeout(timeoutId);
    }
  };

  const openWorkspaceSsoUrl = async (
    authorizationUrl: string,
    expectedUserCode: string,
    deviceAuthorizationBaseUrl: string,
    attemptId: number,
    authRevision: number,
  ): Promise<void> => {
    const current = deviceAuthAttemptRef.current;
    if (
      current?.attemptId !== attemptId ||
      current.authRevision !== authRevision ||
      current.authorizationUrl !== authorizationUrl ||
      current.userCode !== expectedUserCode ||
      current.openInFlight
    ) {
      return;
    }
    current.openInFlight = true;
    try {
      const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
      if (runsInNativeDesktop && invoke) {
        await invoke('open_device_authorization_url', {
          url: authorizationUrl,
          deviceAuthorizationBaseUrl,
          expectedUserCode,
        });
      } else {
        const opened = window.open('about:blank', '_blank');
        if (!opened) throw new Error('popup_blocked');
        try {
          opened.opener = null;
          opened.location.replace(authorizationUrl);
        } catch (error) {
          opened.close();
          throw error;
        }
      }
      if (
        !deviceAuthAttemptIsCurrent(attemptId, authRevision, current.controller)
      )
        return;
      setWorkspaceSso((presentation) =>
        presentation?.authorizationUrl === authorizationUrl
          ? { ...presentation, openError: null }
          : presentation,
      );
    } catch {
      if (
        !deviceAuthAttemptIsCurrent(attemptId, authRevision, current.controller)
      )
        return;
      setWorkspaceSso((presentation) =>
        presentation?.authorizationUrl === authorizationUrl
          ? { ...presentation, openError: t('login.deviceOpenFailed') }
          : presentation,
      );
    } finally {
      const activeAttempt = deviceAuthAttemptRef.current;
      if (activeAttempt?.attemptId === attemptId)
        activeAttempt.openInFlight = false;
    }
  };

  const openCurrentWorkspaceSso = () => {
    const current = deviceAuthAttemptRef.current;
    if (!current?.authorizationUrl) return;
    void openWorkspaceSsoUrl(
      current.authorizationUrl,
      current.userCode,
      configRef.current.deviceAuthorizationBaseUrl,
      current.attemptId,
      current.authRevision,
    );
  };

  const cancelWorkspaceSso = () => {
    const current = deviceAuthAttemptRef.current;
    if (!current) {
      setWorkspaceSso(null);
      return;
    }
    authAttemptRevisionRef.current += 1;
    supersedeWorkspaceSsoAttempt();
    setAuth(emptyAuthState);
    setConnection('idle');
    setError(null);
  };

  const loginWithWorkspaceSso = async (trustedDevice: boolean) => {
    const runtimeConfig = runtimeConfigForLoginAvailability(
      configRef.current,
      runsInNativeDesktop,
    );
    if (runtimeConfig.mode !== 'cloud') return;

    const preserveExpiredPresentation = Boolean(
      workspaceSso && workspaceSso.expiresAt <= Date.now(),
    );
    supersedeWorkspaceSsoAttempt(!preserveExpiredPresentation);
    const authRevision = ++authAttemptRevisionRef.current;
    const attemptId = ++deviceAuthAttemptIdRef.current;
    const controller = new AbortController();
    deviceAuthAttemptRef.current = {
      attemptId,
      authRevision,
      controller,
      authorizationUrl: '',
      userCode: '',
      openInFlight: false,
    };
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);

    let issuedDeviceCode = '';
    let issuedAccessToken = '';
    let tokenAdopted = false;
    let keepExpiredPresentation = false;
    try {
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearNativeTrustedSession();
        } catch {
          throw new WorkspaceSsoFlowError('credential_store');
        }
        if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller))
          return;
      }

      const loginClient = new DesktopApiClient({ ...runtimeConfig, apiKey: '' });
      const deviceAuthorization = await loginClient.createDeviceCode(controller.signal);
      issuedDeviceCode = deviceAuthorization.device_code;
      if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller))
        return;

      const authorizationUrl = resolveDeviceAuthorizationUrl(
        runtimeConfig.deviceAuthorizationBaseUrl,
        deviceAuthorization.verification_uri_complete,
        deviceAuthorization.user_code,
      );
      if (!authorizationUrl) throw new WorkspaceSsoFlowError('invalid_url');

      const activeAttempt = deviceAuthAttemptRef.current;
      if (!activeAttempt || activeAttempt.attemptId !== attemptId) return;
      activeAttempt.authorizationUrl = authorizationUrl;
      activeAttempt.userCode = deviceAuthorization.user_code;
      const deadline = Date.now() + deviceAuthorization.expires_in * 1000;
      setWorkspaceSso({
        userCode: deviceAuthorization.user_code,
        authorizationUrl,
        expiresAt: deadline,
        openError: null,
      });
      void openWorkspaceSsoUrl(
        authorizationUrl,
        deviceAuthorization.user_code,
        runtimeConfig.deviceAuthorizationBaseUrl,
        attemptId,
        authRevision,
      );

      let intervalSeconds = normalizeDeviceAuthorizationInterval(
        deviceAuthorization.interval,
      );
      while (deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) {
        const remainingMs = deadline - Date.now();
        if (remainingMs <= 0) {
          throw new WorkspaceSsoFlowError('expired');
        }
        const waited = await waitForAbortableDelay(
          Math.min(remainingMs, intervalSeconds * 1000),
          controller.signal,
        );
        if (
          !waited ||
          !deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)
        )
          return;

        try {
          const token = await loginClient.pollDeviceToken(
            deviceAuthorization.device_code,
            controller.signal,
          );
          issuedAccessToken = token.access_token;
          if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller))
            return;
          setWorkspaceSso(null);

          const hydrated = await hydrateCloudSession(
            {
              access_token: token.access_token,
              token_type: token.token_type,
              must_change_password: false,
            },
            runtimeConfig,
            authRevision,
          );
          if (
            !hydrated ||
            !deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)
          )
            return;

          let persistenceWarning: string | null = null;
          let persistedNativeSession = false;
          if (trustedDevice && hasNativeTrustedSessionBroker()) {
            try {
              await saveNativeTrustedSession({
                version: 1,
                api_base_url: runtimeConfig.apiBaseUrl,
                runtime_mode: 'cloud',
                credential_kind: 'cloud_bearer',
                credential: token.access_token,
                expires_at: null,
              });
              persistedNativeSession = true;
            } catch {
              persistenceWarning = t('login.persistenceUnavailable');
            }
          }
          if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) {
            if (persistedNativeSession) {
              try {
                await clearNativeTrustedSession();
              } catch {
                // The issued cloud credential is revoked in finally, so a stale broker record
                // cannot recover an authenticated session even if this best-effort clear fails.
              }
            }
            return;
          }
          tokenAdopted = true;
          deviceAuthAttemptRef.current = null;
          controller.abort();
          if (persistenceWarning) setError(persistenceWarning);
          return;
        } catch (caught) {
          if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller))
            return;
          const deviceError = classifyDeviceTokenError(caught);
          if (deviceError?.code === 'authorization_pending') {
            intervalSeconds = normalizeDeviceAuthorizationInterval(
              deviceError.interval,
            );
            continue;
          }
          if (deviceError?.code === 'expired_token') {
            throw new WorkspaceSsoFlowError('expired');
          }
          throw caught;
        }
      }
    } catch (caught) {
      if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller))
        return;
      if (caught instanceof WorkspaceSsoFlowError && caught.code === 'expired') {
        keepExpiredPresentation = true;
        setWorkspaceSso((presentation) =>
          presentation
            ? { ...presentation, expiresAt: Date.now(), openError: null }
            : presentation,
        );
        setAuth(emptyAuthState);
        setConnection('idle');
        setError(null);
        return;
      }
      const message =
        caught instanceof WorkspaceSsoFlowError && caught.code === 'invalid_url'
          ? t('login.deviceInvalidUrl')
          : caught instanceof WorkspaceSsoFlowError &&
              caught.code === 'credential_store'
            ? t('login.credentialStoreUnavailable')
            : t('login.workspaceSsoFailed');
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
    } finally {
      if (issuedAccessToken && !tokenAdopted) {
        await revokeUnadoptedDeviceToken(issuedAccessToken, runtimeConfig);
      }
      if (issuedDeviceCode && !tokenAdopted) {
        await cancelIssuedDeviceCodeBestEffort(issuedDeviceCode, runtimeConfig);
      }
      const current = deviceAuthAttemptRef.current;
      if (current?.attemptId === attemptId) {
        current.controller.abort();
        deviceAuthAttemptRef.current = null;
        if (!keepExpiredPresentation) setWorkspaceSso(null);
      }
    }
  };
  return {
    cancelWorkspaceSso,
    hydrateCloudSession,
    loginWithWorkspaceSso,
    openCurrentWorkspaceSso,
    revokeUnadoptedDeviceToken,
    supersedeWorkspaceSsoAttempt,
  };
}
