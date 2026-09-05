import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DesktopBrowserIntegrationClientV2 } from '../../plugins/desktopBrowserIntegrationAuthorityModuleV2';
import type {
  BrowserAuditEntry,
  BrowserCapabilityGrant,
  BrowserOriginGrant,
  BrowserSiteCredentialMeta,
  DesktopRuntimeConfig,
} from '../../types';

export function useBrowserIntegrationManagementV2(
  client: DesktopBrowserIntegrationClientV2,
  config?: DesktopRuntimeConfig,
) {
  const bridgeClient = config?.mode === 'local' ? client : null;
  const lifetime = useMemo(() => ({ controller: new AbortController() }), [client, config]);
  const currentLifetime = useRef(lifetime);
  currentLifetime.current = lifetime;
  const [originGrants, setOriginGrants] = useState<BrowserOriginGrant[] | null>(null);
  const [originGrantsError, setOriginGrantsError] = useState<string | null>(null);
  const [revokingGrantId, setRevokingGrantId] = useState<string | null>(null);
  const [capabilityGrants, setCapabilityGrants] = useState<BrowserCapabilityGrant[] | null>(null);
  const [capabilityGrantsError, setCapabilityGrantsError] = useState<string | null>(null);
  const [revokingCapabilityGrantId, setRevokingCapabilityGrantId] = useState<string | null>(null);
  const [siteCredentials, setSiteCredentials] = useState<BrowserSiteCredentialMeta[] | null>(null);
  const [siteCredentialsError, setSiteCredentialsError] = useState<string | null>(null);
  const [credentialOrigin, setCredentialOrigin] = useState('');
  const [credentialUsername, setCredentialUsername] = useState('');
  const [credentialPassword, setCredentialPassword] = useState('');
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [deletingCredentialId, setDeletingCredentialId] = useState<string | null>(null);
  const [auditEntries, setAuditEntries] = useState<BrowserAuditEntry[] | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditOriginFilter, setAuditOriginFilter] = useState('');
  const [auditLoading, setAuditLoading] = useState(false);

  useEffect(() => {
    // Effect replay needs a fresh signal; operations retain their original signal.
    if (lifetime.controller.signal.aborted) lifetime.controller = new AbortController();
    return () => lifetime.controller.abort();
  }, [lifetime]);

  const isActive = useCallback(
    () => currentLifetime.current === lifetime && !lifetime.controller.signal.aborted,
    [lifetime],
  );
  const perform = useCallback(
    async <T>(
      request: (signal: AbortSignal) => Promise<T>,
      success: (value: T) => void | Promise<void>,
      failure: (error: string) => void,
      finish?: () => void,
    ) => {
      if (!isActive()) return;
      const signal = lifetime.controller.signal;
      const current = () => isActive() && !signal.aborted;
      try {
        const value = await request(signal);
        if (current()) await success(value);
      } catch (error) {
        if (current()) failure(error instanceof Error ? error.message : String(error));
      } finally {
        if (current()) finish?.();
      }
    },
    [isActive, lifetime],
  );

  const refreshOriginGrants = useCallback(async () => {
    if (!bridgeClient || !isActive()) return;
    await perform(
      (signal) => bridgeClient.listBrowserOriginGrants(signal),
      (value) => {
        setOriginGrants(value);
        setOriginGrantsError(null);
      },
      setOriginGrantsError,
    );
  }, [bridgeClient, isActive, perform]);
  const refreshCapabilityGrants = useCallback(async () => {
    if (!bridgeClient || !isActive()) return;
    await perform(
      (signal) => bridgeClient.listBrowserCapabilityGrants(signal),
      (value) => {
        setCapabilityGrants(value);
        setCapabilityGrantsError(null);
      },
      setCapabilityGrantsError,
    );
  }, [bridgeClient, isActive, perform]);
  const refreshSiteCredentials = useCallback(async () => {
    if (!bridgeClient || !isActive()) return;
    await perform(
      (signal) => bridgeClient.listBrowserSiteCredentials(signal),
      (value) => {
        setSiteCredentials(value);
        setSiteCredentialsError(null);
      },
      setSiteCredentialsError,
    );
  }, [bridgeClient, isActive, perform]);
  const auditRequest = useRef(0);
  const refreshAuditEntries = useCallback(
    async (origin?: string) => {
      if (!bridgeClient || !isActive()) return;
      const request = ++auditRequest.current;
      setAuditLoading(true);
      await perform(
        (signal) => bridgeClient.listBrowserAuditEntries({ limit: 200, origin }, signal),
        (value) => {
          if (request === auditRequest.current) {
            setAuditEntries(value);
            setAuditError(null);
          }
        },
        (error) => {
          if (request === auditRequest.current) setAuditError(error);
        },
        () => {
          if (request === auditRequest.current) setAuditLoading(false);
        },
      );
    },
    [bridgeClient, isActive, perform],
  );

  useEffect(() => {
    setOriginGrants(null);
    setOriginGrantsError(null);
    setRevokingGrantId(null);
    setCapabilityGrants(null);
    setCapabilityGrantsError(null);
    setRevokingCapabilityGrantId(null);
    setSiteCredentials(null);
    setSiteCredentialsError(null);
    setCredentialSaving(false);
    setCredentialOrigin('');
    setCredentialUsername('');
    setCredentialPassword('');
    setDeletingCredentialId(null);
    setAuditEntries(null);
    setAuditError(null);
    setAuditOriginFilter('');
    setAuditLoading(false);
    void refreshOriginGrants();
    void refreshCapabilityGrants();
    void refreshSiteCredentials();
    void refreshAuditEntries();
  }, [refreshOriginGrants, refreshCapabilityGrants, refreshSiteCredentials, refreshAuditEntries]);

  const revokeOriginGrant = async (id: string) => {
    if (!bridgeClient || !isActive() || revokingGrantId) return;
    setRevokingGrantId(id);
    setOriginGrantsError(null);
    await perform(
      (signal) => bridgeClient.revokeBrowserOriginGrant(id, signal),
      refreshOriginGrants,
      setOriginGrantsError,
      () => setRevokingGrantId(null),
    );
  };
  const revokeCapabilityGrant = async (id: string) => {
    if (!bridgeClient || !isActive() || revokingCapabilityGrantId) return;
    setRevokingCapabilityGrantId(id);
    setCapabilityGrantsError(null);
    await perform(
      (signal) => bridgeClient.revokeBrowserCapabilityGrant(id, signal),
      refreshCapabilityGrants,
      setCapabilityGrantsError,
      () => setRevokingCapabilityGrantId(null),
    );
  };
  const saveSiteCredential = async () => {
    if (!bridgeClient || !isActive() || credentialSaving) return;
    setCredentialSaving(true);
    setSiteCredentialsError(null);
    await perform(
      (signal) =>
        bridgeClient.upsertBrowserSiteCredential(
          {
            origin: credentialOrigin,
            username: credentialUsername,
            password: credentialPassword,
          },
          signal,
        ),
      async () => {
        setCredentialOrigin('');
        setCredentialUsername('');
        setCredentialPassword('');
        await refreshSiteCredentials();
      },
      setSiteCredentialsError,
      () => setCredentialSaving(false),
    );
  };
  const deleteSiteCredential = async (id: string) => {
    if (!bridgeClient || !isActive() || deletingCredentialId) return;
    setDeletingCredentialId(id);
    setSiteCredentialsError(null);
    await perform(
      (signal) => bridgeClient.deleteBrowserSiteCredential(id, signal),
      refreshSiteCredentials,
      setSiteCredentialsError,
      () => setDeletingCredentialId(null),
    );
  };
  return {
    bridgeClient,
    originGrants,
    originGrantsError,
    revokingGrantId,
    revokeOriginGrant,
    capabilityGrants,
    capabilityGrantsError,
    revokingCapabilityGrantId,
    revokeCapabilityGrant,
    siteCredentials,
    siteCredentialsError,
    credentialOrigin,
    setCredentialOrigin,
    credentialUsername,
    setCredentialUsername,
    credentialPassword,
    setCredentialPassword,
    credentialSaving,
    saveSiteCredential,
    deletingCredentialId,
    deleteSiteCredential,
    auditEntries,
    auditError,
    auditOriginFilter,
    setAuditOriginFilter,
    auditLoading,
    refreshAuditEntries,
  };
}
