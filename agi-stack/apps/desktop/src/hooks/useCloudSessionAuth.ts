import { useEffect, useRef, useState } from 'react';

import { useI18n } from '../i18n';
import {
  classifyDeviceTokenError,
  DesktopApiClient,
  isWorkspaceContextUnavailableError,
} from '../api/client';
import {
  desktopCloudSessionProjectionClient,
  type CloudSessionProjection,
} from '../api/cloudSessionProjectionClient';
import {
  desktopNativeOAuthClient,
  type NativeOAuthProvider,
  type NativeOAuthSessionEvent,
} from '../api/nativeOAuthClient';
import { desktopNativeCloudAuthClient } from '../api/nativeCloudAuthClient';
import {
  clearNativeTrustedSession,
  hasNativeTrustedSessionBroker,
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
import { createProjectedCloudSessionState } from '../features/auth/nativeOAuthSessionModel';
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
    auth,
    config,
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
    nativeOAuthResumeRoute,
    onNativeOAuthAuthenticated,
    resetProjectScopedState,
    refreshRuntime,
    applySectionSideEffects,
  } = params;
  const [nativeOAuthProviders, setNativeOAuthProviders] = useState<
    readonly NativeOAuthProvider[]
  >([]);
  const [nativeOAuthPendingProvider, setNativeOAuthPendingProvider] = useState<string | null>(null);
  const nativeOAuthPendingProviderRef = useRef<string | null>(null);
  const nativeOAuthExpiryTimerRef = useRef<number | null>(null);
  const nativeOAuthEventHandlerRef = useRef<(event: NativeOAuthSessionEvent) => void>(() => {});
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

  const clearNativeOAuthAttempt = () => {
    if (nativeOAuthExpiryTimerRef.current !== null) {
      window.clearTimeout(nativeOAuthExpiryTimerRef.current);
      nativeOAuthExpiryTimerRef.current = null;
    }
    nativeOAuthPendingProviderRef.current = null;
    setNativeOAuthPendingProvider(null);
  };

  const hydrateProjectedCloudSession = async (
    authAttemptRevision: number,
  ): Promise<CloudSessionProjection | null> => {
    const projectionClient = desktopCloudSessionProjectionClient();
    if (!projectionClient) throw new Error('cloud_session_projection_unavailable');
    const projection = await projectionClient.load();
    if (authAttemptRevisionRef.current !== authAttemptRevision) return null;
    if (!projection) return null;
    const projectedState = createProjectedCloudSessionState(projection, configRef.current);

    contextRevisionRef.current = projection.workspaceContext.revision;
    resetProjectScopedState();
    commitRuntimeConfig(projectedState.config);
    setAuth(projectedState.auth);
    setLoginPassword('');
    setDataset(emptyDataset);
    setConnection('idle');
    setError(null);
    setLastSync(
      new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
    );
    applySectionSideEffects('workspace');
    return projection;
  };

  useEffect(() => {
    if (
      !runsInNativeDesktop ||
      config.mode !== 'cloud' ||
      auth.status === 'signed_in'
    ) {
      setNativeOAuthProviders([]);
      return undefined;
    }
    const client = desktopNativeOAuthClient();
    if (!client) {
      setNativeOAuthProviders([]);
      return undefined;
    }
    let active = true;
    void client
      .listProviders({ apiBaseUrl: config.apiBaseUrl })
      .then((providers) => {
        if (active) setNativeOAuthProviders(providers);
      })
      .catch(() => {
        if (active) setNativeOAuthProviders([]);
      });
    return () => {
      active = false;
    };
  }, [auth.status, config.apiBaseUrl, config.mode, runsInNativeDesktop]);

  useEffect(() => {
    if (!runsInNativeDesktop || config.mode !== 'cloud') return undefined;
    const client = desktopNativeOAuthClient();
    if (!client) return undefined;
    let active = true;
    void client
      .restore()
      .then((pending) => {
        if (!active || pending.status !== 'pending') return;
        nativeOAuthPendingProviderRef.current = pending.provider;
        setNativeOAuthPendingProvider(pending.provider);
        setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
        setConnection('loading');
        setError(null);
        const expiresIn = Math.max(0, pending.expiresAt - Date.now());
        nativeOAuthExpiryTimerRef.current = window.setTimeout(() => {
          if (nativeOAuthPendingProviderRef.current !== pending.provider) return;
          void client.cancel().catch(() => undefined);
          clearNativeOAuthAttempt();
          const message = t('login.workspaceSsoFailed');
          authAttemptRevisionRef.current += 1;
          setAuth({ ...emptyAuthState, error: message });
          setConnection('error');
          setError(message);
        }, expiresIn);
      })
      .catch(() => {
        if (!active) return;
        const message = t('login.workspaceSsoFailed');
        setAuth({ ...emptyAuthState, error: message });
        setConnection('error');
        setError(message);
      });
    return () => {
      active = false;
    };
  }, [config.apiBaseUrl, config.mode, runsInNativeDesktop]);

  nativeOAuthEventHandlerRef.current = (event: NativeOAuthSessionEvent) => {
    const expectedProvider = nativeOAuthPendingProviderRef.current;
    clearNativeOAuthAttempt();
    if (
      event.status === 'failed' ||
      (expectedProvider !== null && expectedProvider !== event.provider)
    ) {
      const message = t('login.workspaceSsoFailed');
      authAttemptRevisionRef.current += 1;
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
      return;
    }

    const authRevision = ++authAttemptRevisionRef.current;
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    void hydrateProjectedCloudSession(authRevision)
      .then((projection) => {
        if (!projection || authAttemptRevisionRef.current !== authRevision) return;
        onNativeOAuthAuthenticated(event.resumeRoute, projection);
      })
      .catch(async () => {
        if (authAttemptRevisionRef.current !== authRevision) return;
        try {
          await clearNativeTrustedSession();
        } catch {
          // The projection failure remains the user-facing error.
        }
        const message = t('login.workspaceSsoFailed');
        setAuth({ ...emptyAuthState, error: message });
        setConnection('error');
        setError(message);
      });
  };

  useEffect(() => {
    if (!runsInNativeDesktop) return undefined;
    const client = desktopNativeOAuthClient();
    if (!client) return undefined;
    const unsubscribe = client.subscribe((event) => nativeOAuthEventHandlerRef.current(event));
    return () => {
      unsubscribe();
      if (nativeOAuthExpiryTimerRef.current !== null) {
        window.clearTimeout(nativeOAuthExpiryTimerRef.current);
        nativeOAuthExpiryTimerRef.current = null;
      }
    };
  }, [runsInNativeDesktop]);

  const beginNativeOAuth = async (provider: string): Promise<void> => {
    const runtimeConfig = runtimeConfigForLoginAvailability(
      configRef.current,
      runsInNativeDesktop,
    );
    const client = desktopNativeOAuthClient();
    if (!client || runtimeConfig.mode !== 'cloud') return;

    if (nativeOAuthPendingProviderRef.current !== null) {
      await client.cancel();
    }
    clearNativeOAuthAttempt();
    const authRevision = ++authAttemptRevisionRef.current;
    nativeOAuthPendingProviderRef.current = provider;
    setNativeOAuthPendingProvider(provider);
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    try {
      await clearNativeTrustedSession();
      if (authAttemptRevisionRef.current !== authRevision) return;
      const opened = await client.begin({
        apiBaseUrl: runtimeConfig.apiBaseUrl,
        provider,
        resumeRoute: nativeOAuthResumeRoute(),
      });
      if (
        authAttemptRevisionRef.current !== authRevision ||
        nativeOAuthPendingProviderRef.current !== provider
      ) {
        return;
      }
      const expiresIn = Math.max(0, opened.expiresAt - Date.now());
      nativeOAuthExpiryTimerRef.current = window.setTimeout(() => {
        if (nativeOAuthPendingProviderRef.current !== provider) return;
        void client.cancel().catch(() => undefined);
        clearNativeOAuthAttempt();
        const message = t('login.workspaceSsoFailed');
        setAuth({ ...emptyAuthState, error: message });
        setConnection('error');
        setError(message);
      }, expiresIn);
    } catch {
      if (authAttemptRevisionRef.current !== authRevision) return;
      clearNativeOAuthAttempt();
      const message = t('login.workspaceSsoFailed');
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
    }
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
    if (current.nativeAttemptId) {
      void desktopNativeCloudAuthClient()
        ?.cancelDeviceAuthorization(current.nativeAttemptId)
        .catch(() => undefined);
    }
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
    let nativeDeviceAttemptId = '';
    let nativeSessionAdopted = false;
    let nativeFlowCompleted = false;
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

      const nativeAuthClient = runsInNativeDesktop ? desktopNativeCloudAuthClient() : null;
      if (nativeAuthClient) {
        const deviceAuthorization = await nativeAuthClient.beginDeviceAuthorization({
          apiBaseUrl: runtimeConfig.apiBaseUrl,
          deviceAuthorizationBaseUrl: runtimeConfig.deviceAuthorizationBaseUrl,
          trustedDevice,
        });
        nativeDeviceAttemptId = deviceAuthorization.attemptId;
        if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;
        const activeAttempt = deviceAuthAttemptRef.current;
        if (!activeAttempt || activeAttempt.attemptId !== attemptId) return;
        activeAttempt.nativeAttemptId = nativeDeviceAttemptId;
        activeAttempt.authorizationUrl = deviceAuthorization.authorizationUrl;
        activeAttempt.userCode = deviceAuthorization.userCode;
        const deadline = deviceAuthorization.expiresAt;
        setWorkspaceSso({
          userCode: deviceAuthorization.userCode,
          authorizationUrl: deviceAuthorization.authorizationUrl,
          expiresAt: deadline,
          openError: null,
        });
        void openWorkspaceSsoUrl(
          deviceAuthorization.authorizationUrl,
          deviceAuthorization.userCode,
          runtimeConfig.deviceAuthorizationBaseUrl,
          attemptId,
          authRevision,
        );
        let intervalSeconds = normalizeDeviceAuthorizationInterval(deviceAuthorization.interval);
        while (deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) {
          const remainingMs = deadline - Date.now();
          if (remainingMs <= 0) throw new WorkspaceSsoFlowError('expired');
          const waited = await waitForAbortableDelay(
            Math.min(remainingMs, intervalSeconds * 1000),
            controller.signal,
          );
          if (!waited || !deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;
          const poll = await nativeAuthClient.pollDeviceAuthorization(nativeDeviceAttemptId);
          if (poll.status === 'authorization_pending') {
            intervalSeconds = normalizeDeviceAuthorizationInterval(poll.interval);
            continue;
          }
          if (poll.status === 'expired') throw new WorkspaceSsoFlowError('expired');
          nativeSessionAdopted = true;
          setWorkspaceSso(null);
          const projection = await hydrateProjectedCloudSession(authRevision);
          if (!projection || !deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) {
            return;
          }
          nativeFlowCompleted = true;
          tokenAdopted = true;
          deviceAuthAttemptRef.current = null;
          controller.abort();
          return;
        }
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

          if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) {
            return;
          }
          tokenAdopted = true;
          deviceAuthAttemptRef.current = null;
          controller.abort();
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
      const nativeAuthClient = runsInNativeDesktop ? desktopNativeCloudAuthClient() : null;
      if (nativeAuthClient && nativeSessionAdopted && !nativeFlowCompleted) {
        await nativeAuthClient.signOut().catch(() => undefined);
      } else if (nativeAuthClient && nativeDeviceAttemptId && !nativeSessionAdopted) {
        await nativeAuthClient
          .cancelDeviceAuthorization(nativeDeviceAttemptId)
          .catch(() => undefined);
      }
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
    beginNativeOAuth,
    cancelWorkspaceSso,
    hydrateCloudSession,
    hydrateProjectedCloudSession,
    loginWithWorkspaceSso,
    nativeOAuthPendingProvider,
    nativeOAuthProviders,
    openCurrentWorkspaceSso,
    revokeUnadoptedDeviceToken,
    supersedeWorkspaceSsoAttempt,
  };
}
