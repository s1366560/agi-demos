import { useCallback, useEffect, useRef, useState } from 'react';

import {
  DesktopApiClient,
  type DesktopMCPServerSummary,
  type DesktopMCPTransport,
  type DesktopMCPTransportConfig,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

export type MCPServerCreateSubmission = {
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

type MCPServerDialogState = { kind: 'create'; key: string } | null;

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
  const [servers, setServers] = useState<DesktopMCPServerSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<MCPServerDialogState>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const requestId = useRef(0);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const request = ++requestId.current;
      setLoading(true);
      setError(null);
      try {
        const loaded = await new DesktopApiClient(config).listMCPServers(config.projectId, signal);
        if (request !== requestId.current || signal?.aborted) return;
        setServers(loaded);
      } catch (caught) {
        if (request !== requestId.current || signal?.aborted) return;
        setServers([]);
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (request === requestId.current) setLoading(false);
      }
    },
    [config],
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
    setDialog({ kind: 'create', key: crypto.randomUUID() });
    setDialogError(null);
  }, []);

  const closeDialog = useCallback(() => {
    setDialog(null);
    setDialogBusy(false);
    setDialogError(null);
  }, []);

  const create = useCallback(
    async (input: MCPServerCreateSubmission) => {
      if (!canManage) return;
      setDialogBusy(true);
      setDialogError(null);
      try {
        const client = new DesktopApiClient(config);
        const idempotencyKey = crypto.randomUUID();
        const transportConfig: DesktopMCPTransportConfig = {
          ...input.transport,
        };
        if (input.credential) {
          const provision = await client.provisionMCPServerCredential({
            project_id: config.projectId,
            server_name: input.name,
            server_type: input.serverType,
            transport_config: input.transport,
            credential_kind: input.credential.kind,
            credential_name: input.credential.name,
            secret: input.credential.secret,
            idempotency_key: `mcp-credential:${idempotencyKey}`,
          });
          if (!provision.stored) throw new Error('MCP credential provisioning failed');
          if (input.credential.kind === 'env') {
            transportConfig.credential_env_names = [input.credential.name];
          } else {
            transportConfig.credential_header_names = [input.credential.name];
          }
        }
        await client.createMCPServer({
          name: input.name,
          description: input.description,
          server_type: input.serverType,
          transport_config: transportConfig,
          enabled: true,
          project_id: config.projectId,
          idempotency_key: `mcp-server:${idempotencyKey}`,
        });
        setDialog(null);
        setDialogBusy(false);
        setDialogError(null);
        await load();
      } catch (caught) {
        setDialogBusy(false);
        setDialogError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [canManage, config, load],
  );

  const testServer = useCallback(
    async (serverId: string) => {
      if (!canManage) return;
      setActionBusyId(serverId);
      setActionMessage(null);
      setError(null);
      try {
        const result = await new DesktopApiClient(config).testMCPServer(serverId);
        setActionMessage(
          result.success
            ? `settings.mcpServers.testSucceeded:${result.tools_discovered}`
            : 'settings.mcpServers.testFailed',
        );
        await load();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setActionBusyId(null);
      }
    },
    [canManage, config, load],
  );

  return {
    servers,
    loading,
    error,
    reload: load,
    dialog,
    dialogBusy,
    dialogError,
    actionBusyId,
    actionMessage,
    openCreate,
    closeDialog,
    create,
    testServer,
  };
}
