import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  DesktopApiClient,
  type DesktopMCPServerSummary,
  type DesktopMCPTransport,
  type DesktopMCPTransportConfig,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import { mcpStdioCommandArgv } from './mcpCommandModel';
import {
  mcpServerRevision,
  mcpToggleAttemptIdentity,
  resolveMCPMutationAttemptKey,
  retainCurrentMCPToggleAttempts,
} from './mcpMutationAttemptModel';

export type MCPServerSubmission = {
  name: string;
  description?: string;
  serverType: DesktopMCPTransport;
  transport: DesktopMCPTransportConfig;
  credential: {
    kind: 'env' | 'header';
    name: string;
    secret: string;
  } | null;
};

type MCPServerDialogState =
  | { kind: 'create'; key: string; contextKey: string }
  | { kind: 'edit'; key: string; contextKey: string; server: DesktopMCPServerSummary }
  | null;

type MCPManagementRequestContext = Readonly<{
  client: DesktopApiClient;
  contextKey: string;
}>;

type MCPSubmissionAttempt = Readonly<{
  dialogKey: string;
  fingerprint: string;
  key: string;
}>;

function canonicalizeSubmissionValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalizeSubmissionValue);
  if (value === null || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([key, item]) => [key, canonicalizeSubmissionValue(item)]),
  );
}

async function mcpSubmissionFingerprint(input: MCPServerSubmission): Promise<string> {
  const canonical = JSON.stringify(canonicalizeSubmissionValue(input));
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function credentialSecretRequired(
  server: DesktopMCPServerSummary,
  input: MCPServerSubmission,
): boolean {
  if (!input.credential) return false;
  const transportConfig = server.transport_config;
  const existingEnvName = transportConfig?.vault_env_names?.[0];
  const existingHeaderName = transportConfig?.vault_header_names?.[0];
  const existingKind = existingEnvName ? 'env' : existingHeaderName ? 'header' : null;
  const existingName = existingEnvName ?? existingHeaderName ?? '';
  if (
    input.credential.kind !== existingKind ||
    input.credential.name !== existingName ||
    input.name !== server.name ||
    input.serverType !== server.server_type
  ) {
    return true;
  }
  if (input.serverType !== 'stdio') {
    return input.transport.url !== transportConfig?.url;
  }
  if (transportConfig?.arguments_redacted) return true;
  const currentArgv = mcpStdioCommandArgv(transportConfig?.command, transportConfig?.args);
  const nextArgv = mcpStdioCommandArgv(input.transport.command, input.transport.args);
  return JSON.stringify(currentArgv) !== JSON.stringify(nextArgv);
}

async function prepareTransportConfig({
  client,
  config,
  input,
  idempotencyKey,
  mutationIdempotencyKey,
  requireCredentialSecret,
}: {
  client: DesktopApiClient;
  config: DesktopRuntimeConfig;
  input: MCPServerSubmission;
  idempotencyKey: string;
  mutationIdempotencyKey: string;
  requireCredentialSecret: boolean;
}): Promise<DesktopMCPTransportConfig> {
  const transportConfig: DesktopMCPTransportConfig = { ...input.transport };
  if (!input.credential) return transportConfig;
  if (requireCredentialSecret && !input.credential.secret) {
    throw new Error('MCP credential secret is required');
  }
  if (input.credential.secret) {
    const provision = await client.provisionMCPServerCredential({
      project_id: config.projectId,
      server_name: input.name,
      server_type: input.serverType,
      transport_config: input.transport,
      credential_kind: input.credential.kind,
      credential_name: input.credential.name,
      secret: input.credential.secret,
      idempotency_key: `mcp-credential:${idempotencyKey}`,
      mutation_idempotency_key: mutationIdempotencyKey,
    });
    if (!provision.stored) throw new Error('MCP credential provisioning failed');
  }
  if (input.credential.kind === 'env') {
    transportConfig.credential_env_names = [input.credential.name];
  } else {
    transportConfig.credential_header_names = [input.credential.name];
  }
  return transportConfig;
}

export function useMCPServerManagement({
  active,
  config,
  contextKey,
  canManage,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
  contextKey: string;
  canManage: boolean;
}) {
  const client = useMemo(() => new DesktopApiClient(config), [config]);
  const [servers, setServers] = useState<DesktopMCPServerSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<MCPServerDialogState>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const requestId = useRef(0);
  const dialogRequestId = useRef(0);
  const actionRequestId = useRef(0);
  const mountedRef = useRef(true);
  const clientRef = useRef(client);
  const contextKeyRef = useRef(contextKey);
  const dialogBusyRef = useRef(false);
  const submissionAttemptRef = useRef<MCPSubmissionAttempt | null>(null);
  const toggleAttemptKeysRef = useRef(new Map<string, string>());
  clientRef.current = client;
  contextKeyRef.current = contextKey;

  const captureRequestContext = useCallback(
    (): MCPManagementRequestContext => ({ client, contextKey }),
    [client, contextKey],
  );
  const requestContextIsCurrent = useCallback(
    (requestContext: MCPManagementRequestContext): boolean =>
      mountedRef.current &&
      clientRef.current === requestContext.client &&
      contextKeyRef.current === requestContext.contextKey,
    [],
  );
  const setDialogBusyState = useCallback((busy: boolean) => {
    dialogBusyRef.current = busy;
    setDialogBusy(busy);
  }, []);
  const resolveSubmissionAttemptKey = useCallback(
    async (dialogKey: string, input: MCPServerSubmission): Promise<string> => {
      const fingerprint = await mcpSubmissionFingerprint(input);
      const current = submissionAttemptRef.current;
      if (current?.dialogKey === dialogKey && current.fingerprint === fingerprint) {
        return current.key;
      }
      const key = crypto.randomUUID();
      submissionAttemptRef.current = { dialogKey, fingerprint, key };
      return key;
    },
    [],
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestId.current += 1;
      dialogRequestId.current += 1;
      actionRequestId.current += 1;
      submissionAttemptRef.current = null;
      toggleAttemptKeysRef.current.clear();
    };
  }, []);

  useEffect(() => {
    requestId.current += 1;
    dialogRequestId.current += 1;
    actionRequestId.current += 1;
    dialogBusyRef.current = false;
    submissionAttemptRef.current = null;
    toggleAttemptKeysRef.current.clear();
    setServers([]);
    setLoading(false);
    setError(null);
    setDialog(null);
    setDialogBusy(false);
    setDialogError(null);
    setActionBusyId(null);
    setActionMessage(null);
  }, [client, contextKey]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const request = ++requestId.current;
      const requestContext = captureRequestContext();
      setLoading(true);
      setError(null);
      try {
        const loaded = await requestContext.client.listMCPServers(config.projectId, signal);
        if (
          request !== requestId.current ||
          signal?.aborted ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        retainCurrentMCPToggleAttempts(toggleAttemptKeysRef.current, contextKey, loaded);
        setServers(loaded);
      } catch (caught) {
        if (
          request !== requestId.current ||
          signal?.aborted ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        setServers([]);
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (
          request === requestId.current &&
          !signal?.aborted &&
          requestContextIsCurrent(requestContext)
        ) {
          setLoading(false);
        }
      }
    },
    [captureRequestContext, config.projectId, contextKey, requestContextIsCurrent],
  );

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => {
      controller.abort();
      requestId.current += 1;
    };
  }, [active, load]);

  const openCreate = useCallback(() => {
    if (dialogBusyRef.current) return;
    submissionAttemptRef.current = null;
    setDialog({ kind: 'create', key: crypto.randomUUID(), contextKey });
    setDialogError(null);
  }, [contextKey]);

  const openEdit = useCallback(
    (server: DesktopMCPServerSummary) => {
      if (dialogBusyRef.current) return;
      submissionAttemptRef.current = null;
      setDialog({ kind: 'edit', key: crypto.randomUUID(), contextKey, server });
      setDialogError(null);
    },
    [contextKey],
  );

  const closeDialog = useCallback(() => {
    if (dialogBusyRef.current) return;
    dialogRequestId.current += 1;
    submissionAttemptRef.current = null;
    setDialog(null);
    setDialogError(null);
  }, []);

  const create = useCallback(
    async (input: MCPServerSubmission) => {
      if (!canManage || dialog?.kind !== 'create' || dialog.contextKey !== contextKey) return;
      const requestContext = captureRequestContext();
      const request = ++dialogRequestId.current;
      setDialogBusyState(true);
      setDialogError(null);
      try {
        const attemptKey = await resolveSubmissionAttemptKey(dialog.key, input);
        if (
          request !== dialogRequestId.current ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        const mutationIdempotencyKey = `mcp-server:${attemptKey}`;
        const transportConfig = await prepareTransportConfig({
          client: requestContext.client,
          config,
          input,
          idempotencyKey: attemptKey,
          mutationIdempotencyKey,
          requireCredentialSecret: true,
        });
        await requestContext.client.createMCPServer({
          name: input.name,
          description: input.description,
          server_type: input.serverType,
          transport_config: transportConfig,
          enabled: true,
          project_id: config.projectId,
          idempotency_key: mutationIdempotencyKey,
        });
        if (
          request !== dialogRequestId.current ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        setDialog(null);
        setDialogBusyState(false);
        setDialogError(null);
        await load();
      } catch (caught) {
        if (
          request !== dialogRequestId.current ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        setDialogBusyState(false);
        setDialogError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [
      canManage,
      captureRequestContext,
      config,
      contextKey,
      dialog,
      load,
      requestContextIsCurrent,
      resolveSubmissionAttemptKey,
      setDialogBusyState,
    ],
  );

  const update = useCallback(
    async (input: MCPServerSubmission) => {
      if (!canManage || dialog?.kind !== 'edit' || dialog.contextKey !== contextKey) return;
      const target = dialog.server;
      const requestContext = captureRequestContext();
      const request = ++dialogRequestId.current;
      setDialogBusyState(true);
      setDialogError(null);
      try {
        const attemptKey = await resolveSubmissionAttemptKey(dialog.key, input);
        if (
          request !== dialogRequestId.current ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        const mutationIdempotencyKey = `mcp-server-update:${attemptKey}`;
        const transportConfig = await prepareTransportConfig({
          client: requestContext.client,
          config,
          input,
          idempotencyKey: attemptKey,
          mutationIdempotencyKey,
          requireCredentialSecret: credentialSecretRequired(target, input),
        });
        await requestContext.client.updateMCPServer(target.id, {
          name: input.name,
          description: input.description ?? null,
          server_type: input.serverType,
          transport_config: transportConfig,
          enabled: target.enabled,
          project_id: config.projectId,
          expected_revision: mcpServerRevision(target),
          idempotency_key: mutationIdempotencyKey,
        });
        if (
          request !== dialogRequestId.current ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        setDialog(null);
        setDialogBusyState(false);
        setDialogError(null);
        await load();
      } catch (caught) {
        if (
          request !== dialogRequestId.current ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        setDialogBusyState(false);
        setDialogError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [
      canManage,
      captureRequestContext,
      config,
      contextKey,
      dialog,
      load,
      requestContextIsCurrent,
      resolveSubmissionAttemptKey,
      setDialogBusyState,
    ],
  );

  const toggleServer = useCallback(
    async (server: DesktopMCPServerSummary) => {
      if (!canManage) return;
      const requestContext = captureRequestContext();
      const request = ++actionRequestId.current;
      setActionBusyId(server.id);
      setActionMessage(null);
      setError(null);
      try {
        const attemptIdentity = mcpToggleAttemptIdentity(contextKey, server);
        const attemptKey = resolveMCPMutationAttemptKey(
          toggleAttemptKeysRef.current,
          attemptIdentity,
          () => crypto.randomUUID(),
        );
        await requestContext.client.setMCPServerEnabled(server.id, {
          enabled: !server.enabled,
          project_id: config.projectId,
          expected_revision: mcpServerRevision(server),
          idempotency_key: `mcp-server-toggle:${attemptKey}`,
        });
        if (
          request !== actionRequestId.current ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        await load();
      } catch (caught) {
        if (
          request === actionRequestId.current &&
          requestContextIsCurrent(requestContext)
        ) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      } finally {
        if (
          request === actionRequestId.current &&
          requestContextIsCurrent(requestContext)
        ) {
          setActionBusyId(null);
        }
      }
    },
    [
      canManage,
      captureRequestContext,
      config.projectId,
      contextKey,
      load,
      requestContextIsCurrent,
    ],
  );

  const remove = useCallback(async () => {
    if (!canManage || dialog?.kind !== 'edit' || dialog.contextKey !== contextKey) return;
    const target = dialog.server;
    const requestContext = captureRequestContext();
    const request = ++dialogRequestId.current;
    setDialogBusyState(true);
    setDialogError(null);
    try {
      await requestContext.client.deleteMCPServer(target.id, {
        project_id: config.projectId,
        expected_revision: mcpServerRevision(target),
        idempotency_key: `mcp-server-delete:${dialog.key}`,
      });
      if (request !== dialogRequestId.current || !requestContextIsCurrent(requestContext)) {
        return;
      }
      setDialog(null);
      setDialogBusyState(false);
      setDialogError(null);
      await load();
    } catch (caught) {
      if (request !== dialogRequestId.current || !requestContextIsCurrent(requestContext)) {
        return;
      }
      setDialogBusyState(false);
      setDialogError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [
    canManage,
    captureRequestContext,
    config.projectId,
    contextKey,
    dialog,
    load,
    requestContextIsCurrent,
    setDialogBusyState,
  ]);

  const testServer = useCallback(
    async (serverId: string) => {
      if (!canManage) return;
      const requestContext = captureRequestContext();
      const request = ++actionRequestId.current;
      setActionBusyId(serverId);
      setActionMessage(null);
      setError(null);
      try {
        const result = await requestContext.client.testMCPServer(serverId);
        if (
          request !== actionRequestId.current ||
          !requestContextIsCurrent(requestContext)
        ) {
          return;
        }
        setActionMessage(
          result.success
            ? `settings.mcpServers.testSucceeded:${result.tools_discovered}`
            : 'settings.mcpServers.testFailed',
        );
        await load();
      } catch (caught) {
        if (
          request === actionRequestId.current &&
          requestContextIsCurrent(requestContext)
        ) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      } finally {
        if (
          request === actionRequestId.current &&
          requestContextIsCurrent(requestContext)
        ) {
          setActionBusyId(null);
        }
      }
    },
    [canManage, captureRequestContext, load, requestContextIsCurrent],
  );

  return {
    servers,
    loading,
    error,
    reload: load,
    dialog: dialog?.contextKey === contextKey ? dialog : null,
    dialogBusy,
    dialogError,
    actionBusyId,
    actionMessage,
    openCreate,
    openEdit,
    closeDialog,
    create,
    update,
    toggleServer,
    remove,
    testServer,
  };
}
