/**
 * McpPromptsTabV2 - Prompts Tab with Modern UI (SEP-1865 P2-2)
 * Displays MCP server prompts with expandable argument details
 */

import React, { useEffect, useMemo, useState } from 'react';

import { Spin, Input, Select, Tag } from 'antd';
import { Search, MessageSquare, Server, ChevronDown, ChevronRight } from 'lucide-react';

import { useMCPStore } from '@/stores/mcp';
import { useProjectStore } from '@/stores/project';

import { mcpAPI } from '@/services/mcpService';

import { CARD_STYLES } from './styles';

const { Search: AntSearch } = Input;

interface PromptArg {
  name: string;
  description?: string;
  required?: boolean;
}

interface PromptInfo {
  name: string;
  description?: string;
  arguments?: PromptArg[];
}

interface PromptWithServer extends PromptInfo {
  serverName: string;
  serverId: string;
}

export const McpPromptsTabV2: React.FC = () => {
  const [search, setSearch] = useState('');
  const [serverFilter, setServerFilter] = useState<string>('all');
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [allPrompts, setAllPrompts] = useState<PromptWithServer[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const servers = useMCPStore((s) => s.servers);
  const listServers = useMCPStore((s) => s.listServers);
  const currentProject = useProjectStore((s) => s.currentProject);

  // Ensure servers are loaded
  useEffect(() => {
    if (servers.length === 0 && currentProject?.id) {
      listServers({ project_id: currentProject.id });
    }
  }, [servers.length, currentProject?.id, listServers]);

  // Fetch prompts from all enabled servers
  useEffect(() => {
    const fetchPrompts = async () => {
      setIsLoading(true);
      const results: PromptWithServer[] = [];

      const enabledServers = servers.filter((s) => s.enabled);
      const settled = await Promise.allSettled(
        enabledServers.map(async (server) => {
          try {
            const resp = await mcpAPI.getPrompts(server.id);
            return (resp.prompts ?? []).map((p) => ({
              ...p,
              serverName: server.name,
              serverId: server.id,
            }));
          } catch {
            return [];
          }
        })
      );

      for (const result of settled) {
        if (result.status === 'fulfilled') {
          results.push(...result.value);
        }
      }

      setAllPrompts(results);
      setIsLoading(false);
    };

    if (servers.length > 0) {
      void fetchPrompts();
    } else {
      setIsLoading(false);
    }
  }, [servers]);

  const filteredPrompts = useMemo(() => {
    return allPrompts.filter((prompt) => {
      if (serverFilter !== 'all' && prompt.serverId !== serverFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        if (
          !prompt.name.toLowerCase().includes(q) &&
          !(prompt.description ?? '').toLowerCase().includes(q)
        ) {
          return false;
        }
      }
      return true;
    });
  }, [allPrompts, search, serverFilter]);

  const serverOptions = useMemo(
    () => [
      { label: 'All Servers', value: 'all' },
      ...servers.map((s) => ({ label: s.name, value: s.id })),
    ],
    [servers]
  );

  const serversWithPrompts = new Set(allPrompts.map((p) => p.serverId)).size;

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Spin size="large" />
        <p className="text-sm text-slate-400 mt-4">Loading prompts...</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header Stats */}
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-50 to-blue-50 dark:from-indigo-900/20 dark:to-blue-900/20 flex items-center justify-center">
                <MessageSquare size={20} className="text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {allPrompts.length}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">Total Prompts</p>
              </div>
            </div>
            <div className="w-px h-10 bg-slate-200 dark:bg-slate-700" />
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-50 to-cyan-50 dark:from-blue-900/20 dark:to-cyan-900/20 flex items-center justify-center">
                <Server size={20} className="text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {serversWithPrompts}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">Servers with Prompts</p>
              </div>
            </div>
          </div>
          {filteredPrompts.length !== allPrompts.length && (
            <span className="text-sm text-slate-500 dark:text-slate-400">
              Showing {filteredPrompts.length} / {allPrompts.length}
            </span>
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <AntSearch
              placeholder="Search prompt name or description..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              allowClear
              prefix={<Search size={16} className="text-slate-400" />}
              className="w-full"
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

      {/* Prompt List */}
      {filteredPrompts.length === 0 ? (
        <div
          className={`flex flex-col items-center justify-center py-16 text-center ${CARD_STYLES.base} border-dashed`}
        >
          <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-4">
            <MessageSquare size={28} className="text-slate-300 dark:text-slate-500" />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-1">
            {allPrompts.length === 0 ? 'No Prompts Found' : 'No Matching Prompts'}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
            {allPrompts.length === 0
              ? 'MCP servers have not exposed any prompts'
              : 'Try adjusting your search or filter'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredPrompts.map((prompt, idx) => {
            const key = `${prompt.serverId}-${prompt.name}-${idx}`;
            const isExpanded = expandedKey === key;
            const hasArgs = (prompt.arguments?.length ?? 0) > 0;

            return (
              <div
                key={key}
                className={`${CARD_STYLES.base} overflow-hidden transition-all duration-200 hover:shadow-md`}
              >
                <button
                  type="button"
                  className="w-full p-4 flex items-start gap-3 text-left"
                  onClick={() => {
                    setExpandedKey(isExpanded ? null : key);
                  }}
                >
                  <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-50 to-blue-50 dark:from-indigo-900/20 dark:to-blue-900/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <MessageSquare
                      size={16}
                      className="text-indigo-600 dark:text-indigo-400"
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white truncate">
                        {prompt.name}
                      </span>
                      {hasArgs && (
                        <Tag color="blue" className="text-xs">
                          {prompt.arguments!.length} arg{prompt.arguments!.length !== 1 ? 's' : ''}
                        </Tag>
                      )}
                    </div>
                    {prompt.description && (
                      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                        {prompt.description}
                      </p>
                    )}
                    <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
                      {prompt.serverName}
                    </p>
                  </div>
                  <div className="flex-shrink-0 text-slate-400 mt-1">
                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </div>
                </button>

                {isExpanded && hasArgs && (
                  <div className="border-t border-slate-200 dark:border-slate-700 px-4 py-3 bg-slate-50 dark:bg-slate-800/50">
                    <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-2 uppercase tracking-wide">
                      Arguments
                    </p>
                    <div className="space-y-2">
                      {prompt.arguments!.map((arg) => (
                        <div
                          key={arg.name}
                          className="flex items-start gap-2 text-sm"
                        >
                          <code className="text-xs font-mono bg-slate-200 dark:bg-slate-700 px-1.5 py-0.5 rounded text-slate-700 dark:text-slate-300">
                            {arg.name}
                          </code>
                          {arg.required && (
                            <span className="text-red-500 text-xs font-medium">required</span>
                          )}
                          {arg.description && (
                            <span className="text-slate-500 dark:text-slate-400 text-xs">
                              {arg.description}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
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
