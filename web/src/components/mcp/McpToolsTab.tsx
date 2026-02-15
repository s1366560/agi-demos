/**
 * McpToolsTab - Cross-server tool browsing tab.
 * Shows all tools from all servers with search and server filter.
 */

import React, { useEffect, useMemo, useState } from 'react';

import { Select, Spin, Input, Tag, Tooltip } from 'antd';
import { Search, Wrench, Server, ChevronDown, ChevronUp, FileJson } from 'lucide-react';


import { useMCPStore } from '@/stores/mcp';
import { useProjectStore } from '@/stores/project';

import type { MCPToolInfo } from '@/types/agent';

const { Search: AntSearch } = Input;

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
      <div className="flex flex-col items-center justify-center py-16">
        <Spin size="large" />
        <p className="text-sm text-slate-400 mt-4">Loading tools...</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header Stats */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
            <Wrench size={16} className="text-primary-500" />
            <span>
              <span className="font-semibold text-slate-900 dark:text-white">{allTools.length}</span> tools
            </span>
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
            <Server size={16} className="text-violet-500" />
            <span>
              <span className="font-semibold text-slate-900 dark:text-white">{servers.filter(s => s.discovered_tools?.length).length}</span> servers
            </span>
          </div>
        </div>
        {filteredTools.length !== allTools.length && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Showing {filteredTools.length} of {allTools.length}
          </span>
        )}
      </div>

      {/* Toolbar */}
      <div className="bg-white dark:bg-slate-800 rounded-xl p-4 border border-slate-200 dark:border-slate-700 shadow-sm">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <AntSearch
              placeholder="Search tools by name or description..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              allowClear
              prefix={<Search size={16} className="text-slate-400" />}
            />
          </div>
          <Select
            value={serverFilter}
            onChange={setServerFilter}
            className="w-full sm:w-52"
            placeholder="Filter by server"
            options={serverOptions}
            suffixIcon={<Server size={14} className="text-slate-400" />}
          />
        </div>
      </div>

      {/* Tool list */}
      {filteredTools.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 border-dashed">
          <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-4">
            <Wrench size={28} className="text-slate-300 dark:text-slate-500" />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-1">
            {allTools.length === 0 ? 'No tools discovered yet' : 'No tools match your search'}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
            {allTools.length === 0
              ? 'Sync your MCP servers to discover available tools.'
              : 'Try adjusting your search or filter criteria.'}
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
                className={`bg-white dark:bg-slate-800 rounded-xl border transition-all duration-200 overflow-hidden ${
                  isExpanded 
                    ? 'shadow-md border-primary-200 dark:border-primary-800/50 ring-1 ring-primary-50 dark:ring-primary-900/20' 
                    : 'border-slate-200 dark:border-slate-700 hover:shadow-sm hover:border-slate-300 dark:hover:border-slate-600'
                }`}
              >
                {/* Header - Always visible */}
                <div
                  className="p-4 cursor-pointer"
                  onClick={() => setExpandedKey(isExpanded ? null : key)}
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        isExpanded 
                          ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-500' 
                          : 'bg-slate-50 dark:bg-slate-700/50 text-slate-400 dark:text-slate-500'
                      }`}>
                        <Wrench size={16} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h4 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                            {tool.name}
                          </h4>
                          {tool.input_schema && (
                            <Tooltip title="Has input schema">
                              <FileJson size={12} className="text-slate-400 flex-shrink-0" />
                            </Tooltip>
                          )}
                        </div>
                        {tool.description ? (
                          <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-1 mt-0.5">
                            {tool.description}
                          </p>
                        ) : (
                          <p className="text-xs text-slate-400 dark:text-slate-500 italic mt-0.5">
                            No description
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <Tag className="text-xs m-0" color="default">
                        {tool.serverName}
                      </Tag>
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center transition-colors ${
                        isExpanded 
                          ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400' 
                          : 'bg-slate-100 dark:bg-slate-700 text-slate-400 dark:text-slate-500'
                      }`}>
                        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700/50">
                    {/* Server info */}
                    <div className="flex items-center gap-4 py-3 text-xs text-slate-500 dark:text-slate-400">
                      <div className="flex items-center gap-1.5">
                        <Server size={12} />
                        <span className="font-medium text-slate-700 dark:text-slate-300">{tool.serverName}</span>
                      </div>
                      <span className="text-slate-300 dark:text-slate-600">•</span>
                      <span className="capitalize">{tool.serverType}</span>
                    </div>
                    
                    {/* Description */}
                    {tool.description && (
                      <div className="mb-4">
                        <p className="text-sm text-slate-600 dark:text-slate-400 leading-relaxed">
                          {tool.description}
                        </p>
                      </div>
                    )}
                    
                    {/* Input Schema */}
                    {tool.input_schema && (
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <FileJson size={12} className="text-slate-400" />
                          <span className="text-xs font-medium text-slate-700 dark:text-slate-300">Input Schema</span>
                        </div>
                        <pre className="p-3 bg-slate-50 dark:bg-slate-900/80 rounded-lg text-xs text-slate-700 dark:text-slate-300 overflow-auto max-h-64 border border-slate-100 dark:border-slate-800">
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
