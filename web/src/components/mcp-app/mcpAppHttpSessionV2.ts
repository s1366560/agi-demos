import { mcpAppAPI } from '@/services/mcpAppService';

import type { WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';

/** Select one structural route before dispatch. A dispatched mutation is never replayed. */
export async function callMcpAppHttpSessionV2(
  operation: WebOperationContextV2,
  identity: {
    projectId: string;
    serverName?: string | undefined;
    appId?: string | undefined;
    toolName: string;
  },
  params: { name: string; arguments?: Record<string, unknown> | undefined },
  assertFallback: () => void,
  unavailableMessage: string
): Promise<CallToolResult> {
  const request = { tool_name: params.name, arguments: structuredClone(params.arguments ?? {}) };
  return operation.runChild(async (child) => {
    child.check();
    assertFallback();
    const options = { operation: child, signal: child.signal };
    let target = identity.appId;
    if (target?.startsWith('_synthetic_')) target = undefined;
    if (!target) {
      let apps: Awaited<ReturnType<typeof mcpAppAPI.list>>;
      try {
        apps = await mcpAppAPI.list(identity.projectId, false, options);
      } catch (error) {
        child.check();
        assertFallback();
        if (!identity.appId?.startsWith('_synthetic_') || !identity.serverName) throw error;
        apps = [];
      }
      child.check();
      assertFallback();
      target = apps.find(
        (app) =>
          app.project_id === identity.projectId &&
          app.server_name === identity.serverName &&
          app.tool_name === identity.toolName
      )?.id;
    }
    child.check();
    assertFallback();
    const result = target
      ? await mcpAppAPI.proxyToolCall(target, request, options)
      : identity.serverName
        ? await mcpAppAPI.proxyToolCallDirect(
            { ...request, project_id: identity.projectId, server_name: identity.serverName },
            options
          )
        : undefined;
    child.check();
    if (!result) return { content: [{ type: 'text', text: unavailableMessage }], isError: true };
    return { content: result.content as CallToolResult['content'], isError: result.is_error };
  });
}
