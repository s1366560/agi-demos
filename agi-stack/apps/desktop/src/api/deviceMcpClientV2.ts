import type { DesktopRuntimeConfig } from '../types';
import type { DesktopProjectMcpServersClientV2 } from '../plugins/desktopProjectMcpServersAuthorityModuleV2';
import {
  freezeMcpServersConfigV2,
  freezeMcpServersJsonV2,
  mcpServersErrorV2,
  type McpServersArgumentsV2,
  type McpServersMethodV2,
} from '../plugins/desktopProjectMcpServersOperationContractV2';
import { requireMcpServersResultV2 } from '../plugins/desktopProjectMcpServersResponseContractV2';
import {
  requireDeviceMcpEnvelopeV2,
  requireDeviceMcpRequestV2,
  type DeviceMcpOperationV2,
} from './deviceMcpContractV2';

type NativeInvoke = (command: string, args: Record<string, unknown>) => Promise<unknown>;

export function createDeviceMcpClientV2(
  config: DesktopRuntimeConfig,
  isCurrent: () => boolean,
  suppliedInvoke?: NativeInvoke,
): DesktopProjectMcpServersClientV2 {
  const runtime = freezeMcpServersConfigV2(config);
  const scope = Object.freeze({
    authority: runtime.mode,
    tenantId: runtime.tenantId,
    projectId: runtime.projectId,
  });
  const invoke: NativeInvoke =
    suppliedInvoke ??
    ((command, args) => {
      const desktop = typeof window === 'undefined' ? undefined : window.__MEMSTACK_DESKTOP__;
      if (desktop?.runtime !== 'electron' || !desktop.core?.invoke)
        return Promise.reject(mcpServersErrorV2('device_mcp_native_unavailable', 503));
      return desktop.core.invoke(command, args);
    });
  let contextToken: string | undefined;
  let listSequence = 0;
  const ensureCurrent = (signal?: AbortSignal): void => {
    signal?.throwIfAborted();
    if (runtime.mode !== 'cloud' || !isCurrent()) {
      contextToken = undefined;
      throw mcpServersErrorV2('device_mcp_context_changed', 409);
    }
  };
  const call = async <K extends McpServersMethodV2>(
    method: K,
    args: McpServersArgumentsV2[K],
    operation: DeviceMcpOperationV2,
    signal?: AbortSignal,
  ) => {
    ensureCurrent(signal);
    const listing = operation.action === 'list';
    const sequence = listing ? ++listSequence : listSequence;
    const token = contextToken;
    if (!listing && !token) throw mcpServersErrorV2('device_mcp_context_required', 409);
    const request = requireDeviceMcpRequestV2(
      freezeMcpServersJsonV2({
        input: {
          tenant_id: scope.tenantId,
          project_id: scope.projectId,
          ...(listing ? {} : { context_token: token }),
          operation,
        },
      }),
    );
    let raw: unknown;
    try {
      raw = await invoke('device_mcp_manage_v2', request);
    } catch (error) {
      contextToken = undefined;
      throw error;
    }
    ensureCurrent(signal);
    if (sequence !== listSequence || (!listing && contextToken !== token))
      throw mcpServersErrorV2('device_mcp_context_changed', 409);
    const envelope = requireDeviceMcpEnvelopeV2(raw, scope.tenantId, scope.projectId);
    if (!listing && envelope.context.token !== token) {
      contextToken = undefined;
      throw mcpServersErrorV2('device_mcp_context_changed', 409);
    }
    const result = requireMcpServersResultV2(
      method,
      envelope.result,
      { config: runtime, scope, args },
      true,
    );
    if (listing) contextToken = envelope.context.token;
    return result;
  };
  const unavailable = async (): Promise<never> => {
    throw mcpServersErrorV2('device_mcp_oauth_unavailable', 422);
  };
  return Object.freeze({
    listMCPServers: (projectId, signal) => {
      if (projectId !== scope.projectId)
        return Promise.reject(mcpServersErrorV2('device_mcp_scope_mismatch', 409));
      return call('listMCPServers', [projectId], { action: 'list' }, signal);
    },
    provisionMCPServerCredential: (body, signal) =>
      call(
        'provisionMCPServerCredential',
        [body],
        { action: 'provision_credential', body },
        signal,
      ),
    createMCPServer: (body, signal) =>
      call('createMCPServer', [body], { action: 'create', body }, signal),
    updateMCPServer: (server_id, body, signal) =>
      call('updateMCPServer', [server_id, body], { action: 'update', server_id, body }, signal),
    setMCPServerEnabled: (server_id, body, signal) =>
      call('setMCPServerEnabled', [server_id, body], { action: 'update', server_id, body }, signal),
    deleteMCPServer: (server_id, body, signal) =>
      call('deleteMCPServer', [server_id, body], { action: 'delete', server_id, body }, signal),
    testMCPServer: (server_id, signal) =>
      call('testMCPServer', [server_id], { action: 'test', server_id }, signal),
    getMCPOAuthStatus: unavailable,
    mutateMCPOAuth: unavailable,
  } satisfies DesktopProjectMcpServersClientV2);
}
