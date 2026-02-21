/**
 * McpToolsDrawer - Drawer showing tools for a specific MCP server.
 * Replaces the previous ToolsModal with an Ant Design Drawer.
 */

import React from 'react';

import { Drawer, Empty } from 'antd';

import type { MCPServerResponse, MCPToolInfo } from '@/types/agent';

export interface McpToolsDrawerProps {
  open: boolean;
  server: MCPServerResponse | null;
  onClose: () => void;
}

export const McpToolsDrawer: React.FC<McpToolsDrawerProps> = ({ open, server, onClose }) => {
  const tools = server?.discovered_tools ?? [];

  return (
    <Drawer
      title={server ? `${server.name} - Tools` : 'Server Tools'}
      open={open}
      onClose={onClose}
      size="large"
      destroyOnClose
    >
      {tools.length === 0 ? (
        <Empty description="No tools discovered. Try syncing the server." />
      ) : (
        <div className="space-y-3">
          {tools.map((tool: MCPToolInfo, idx: number) => (
            <div
              key={idx}
              className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-200 dark:border-slate-700"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="material-symbols-outlined text-base text-primary-500">build</span>
                <span className="font-medium text-slate-900 dark:text-white">{tool.name}</span>
              </div>
              {tool.description && (
                <p className="text-sm text-slate-600 dark:text-slate-400 mb-2">
                  {tool.description}
                </p>
              )}
              {tool.input_schema && (
                <details className="mt-2">
                  <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-700 dark:hover:text-slate-300">
                    Input Schema
                  </summary>
                  <pre className="mt-1 p-2 bg-slate-100 dark:bg-slate-900 rounded text-xs text-slate-700 dark:text-slate-300 overflow-auto max-h-40">
                    {JSON.stringify(tool.input_schema, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </Drawer>
  );
};
