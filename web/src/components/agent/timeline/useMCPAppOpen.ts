import { useCallback } from 'react';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';

import { getToolLabel } from './ExecutionTimeline';

import type { TimelineStep } from './ExecutionTimeline';

/**
 * Hook for handling MCP app opening from timeline steps
 * Implements 4-priority lookup strategy:
 * 1. Find existing tab for this tool
 * 2. Use UI metadata from observe event
 * 3. Look up app from store
 * 4. Fetch app from API if not found
 */
export const useMCPAppOpen = (step: TimelineStep) => {
  return useCallback(
    async (e: React.MouseEvent<HTMLButtonElement>) => {
      e.stopPropagation();

      const canvasState = useCanvasStore.getState();
      const mcpState = useMCPAppStore.getState();
      const ui = step.mcpUiMetadata;

      // Priority 1: Find existing tab for this tool
      const existingMcpTab = canvasState.tabs.find(
        (t) => t.type === 'mcp-app' && t.mcpToolName === step.toolName
      );
      if (existingMcpTab) {
        canvasState.setActiveTab(existingMcpTab.id);
        useLayoutModeStore.getState().setMode('canvas');
        return;
      }

      // Priority 2: Use UI metadata from observe event (persisted with events)
      if (ui?.resource_uri) {
        // Priority: ui.project_id > project store > conversation store
        const projectStoreId = useProjectStore.getState().currentProject?.id;
        const conversationProjectId =
          useConversationsStore.getState().currentConversation?.project_id;
        const currentProjectId = ui.project_id || projectStoreId || conversationProjectId || '';
        const tabId = `mcp-app-${ui.resource_uri}`;

        // Look up cached HTML from mcp_app_result event
        const cachedHtml = mcpState.getHtmlByUri(ui.resource_uri);

        canvasState.openTab({
          id: tabId,
          title: ui.title || getToolLabel(step.toolName),
          type: 'mcp-app' as const,
          content: '',
          mcpResourceUri: ui.resource_uri,
          mcpAppHtml: cachedHtml || undefined,
          mcpToolName: step.toolName,
          mcpProjectId: currentProjectId,
          mcpAppToolResult: step.output,
          mcpServerName: ui.server_name,
          mcpAppId: ui.app_id,
        });
        useLayoutModeStore.getState().setMode('canvas');
        return;
      }

      // Priority 3: Look up app from store
      let apps = mcpState.apps;
      // Priority: ui.project_id > project store > conversation store
      const uiProjectId = ui?.project_id;
      const projectStoreId = useProjectStore.getState().currentProject?.id;
      const conversationProjectId =
        useConversationsStore.getState().currentConversation?.project_id;
      const currentProjectId = uiProjectId || projectStoreId || conversationProjectId || '';

      let match = Object.values(apps).find(
        (a) =>
          step.toolName === `mcp__${a.server_name}__${a.tool_name}` ||
          step.toolName.replace(/-/g, '_') ===
            `mcp__${(a.server_name || '').replace(/-/g, '_')}__${a.tool_name}` ||
          a.tool_name === step.toolName
      );

      // Priority 4: If no match in store, fetch from API
      if (!match && currentProjectId) {
        try {
          await mcpState.fetchApps(currentProjectId);
          apps = useMCPAppStore.getState().apps;
          match = Object.values(apps).find(
            (a) =>
              step.toolName === `mcp__${a.server_name}__${a.tool_name}` ||
              step.toolName.replace(/-/g, '_') ===
                `mcp__${(a.server_name || '').replace(/-/g, '_')}__${a.tool_name}` ||
              a.tool_name === step.toolName
          );
        } catch {
          // Ignore fetch errors - fall through to open without match
        }
      }

      const resourceUri = match?.ui_metadata?.resourceUri;
      const tabKey = resourceUri || match?.id || step.id;
      const tabId = `mcp-app-${tabKey}`;

      // Look up cached HTML from mcp_app_result event
      const cachedHtml = resourceUri ? mcpState.getHtmlByUri(resourceUri) : null;

      canvasState.openTab({
        id: tabId,
        title: (match?.ui_metadata?.title as string) || getToolLabel(step.toolName),
        type: 'mcp-app' as const,
        content: '',
        mcpResourceUri: resourceUri,
        mcpAppHtml: cachedHtml || undefined,
        mcpToolName: step.toolName,
        mcpProjectId: currentProjectId,
        mcpAppToolResult: step.output,
        mcpAppUiMetadata: match?.ui_metadata as Record<string, unknown> | undefined,
        mcpServerName: match?.server_name,
        mcpAppId: match?.id,
      });
      useLayoutModeStore.getState().setMode('canvas');
    },
    [step]
  );
};
