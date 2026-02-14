/**
 * McpToolsTab - Cross-server tool browsing tab.
 * Shows all tools from all servers with search and server filter.
 */

import React, { useEffect, useMemo, useState } from 'react';

import { Select, Spin, Input, Tag } from 'antd';

import { useMCPStore } from '@/stores/mcp';
import { useProjectStore } from '@/stores/project';

import type { MCPToolInfo } from '@/types/agent';

const { Search } = Input;

interface ToolWithServer extends MCPToolInfo {
  serverName: string;
  serverId: string;
  serverType: string;
}

export const McpToolsTab: React.FC = () => {
  const [search, setSearch] = useState('');
  const [serverFilter, setServerFilter] = useState<string>('all');
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const servers = useMCPStore((s) => s.servers);
  const isLoading = useMCPStore((s) => s.isLoading);
  const listServers = useMCPStore((s) => s.listServers);
  const currentProject = useProjectStore((s) => s.currentProject);

  // Ensure servers are loaded (handles case where Tools tab is first viewed)
  useEffect(() => {
    if (servers.length === 0 && currentProject?.id) {
      listServers({ project_id: currentProject.id });
    }
  }, [servers.length, currentProject?.id, listServers]);

  const allTools = useMemo<ToolWithServer[]>(
    () =>
      servers.flatMap((server) =>
        (server.discovered_tools ?? []).map((tool) => ({
          ...tool,
          serverName: server.name,
          serverId: server.id,
          serverType: server.server_type,
        }))
      ),
    [servers]
  );

  const filteredTools = useMemo(() => {
    return allTools.filter((tool) => {
      if (serverFilter !== 'all' && tool.serverId !== serverFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        if (
          !tool.name.toLowerCase().includes(q) &&
          !(tool.description ?? '').toLowerCase().includes(q)
        ) {
          return false;
        }
      }
      return true;
    });
  }, [allTools, search, serverFilter]);

  const serverOptions = useMemo(
    () => [
      { label: 'All Servers', value: 'all' },
      ...servers.map((s) => ({ label: s.name, value: s.id })),
    ],
    [servers]
  );

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Toolbar */}
      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <Search
              placeholder="Search tools by name or description..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              allowClear
            />
          </div>
          <Select
            value={serverFilter}
            onChange={setServerFilter}
            className="w-full sm:w-48"
            options={serverOptions}
          />
        </div>
      </div>

      {/* Tool list */}
      {filteredTools.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <span className="material-symbols-outlined text-5xl text-slate-300 dark:text-slate-600 mb-4">
            build
          </span>
          <p className="text-slate-500 dark:text-slate-400">
            {allTools.length === 0
              ? 'No tools discovered yet. Sync your servers to discover tools.'
              : 'No tools match your search.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredTools.map((tool, idx) => {
            const key = `${tool.serverId}-${tool.name}-${idx}`;
            const isExpanded = expandedKey === key;

            return (
              <div
                key={key}
                className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700 hover:shadow-md transition-shadow cursor-pointer"
                onClick={() => setExpandedKey(isExpanded ? null : key)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="material-symbols-outlined text-lg text-primary-500 flex-shrink-0">
                      build
                    </span>
                    <div className="min-w-0">
                      <h4 className="text-sm font-medium text-slate-900 dark:text-white">
                        {tool.name}
                      </h4>
                      {tool.description && (
                        <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-1 mt-0.5">
                          {tool.description}
                        </p>
                      )}
                    </div>
                  </div>
                  <Tag className="text-xs flex-shrink-0">{tool.serverName}</Tag>
                </div>

                {isExpanded && (
                  <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">
                    {tool.description && (
                      <p className="text-sm text-slate-600 dark:text-slate-400 mb-3">
                        {tool.description}
                      </p>
                    )}
                    <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                      <span>Server: {tool.serverName}</span>
                      <span className="text-slate-300 dark:text-slate-600">|</span>
                      <span>Type: {tool.serverType}</span>
                    </div>
                    {tool.input_schema && (
                      <div>
                        <p className="text-xs text-slate-500 mb-1">Input Schema:</p>
                        <pre className="p-2 bg-slate-50 dark:bg-slate-900 rounded text-xs text-slate-700 dark:text-slate-300 overflow-auto max-h-48">
                          {JSON.stringify(tool.input_schema, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
