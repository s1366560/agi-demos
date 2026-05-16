/**
 * McpPromptsTabV2 - Prompts Tab with Modern UI (SEP-1865 P2-2)
 * Displays MCP server prompts with expandable argument details
 */

import React, { useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Input, Select, Spin, Tag } from 'antd';
import { ChevronDown, ChevronRight, MessageSquare, Search, Server } from 'lucide-react';

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
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [serverFilter, setServerFilter] = useState<string>('all');
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [allPrompts, setAllPrompts] = useState<PromptWithServer[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const servers = useMCPStore((s) => s.servers);
  const listServers = useMCPStore((s) => s.listServers);
  const currentProject = useProjectStore((s) => s.currentProject);

  // Ensure servers are loaded
  useEffect(() => {
    if (servers.length === 0 && currentProject?.id) {
      void listServers({ project_id: currentProject.id });
    }
  }, [servers.length, currentProject?.id, listServers]);

  // Fetch prompts from all enabled servers
  useEffect(() => {
    const fetchPrompts = async () => {
      setIsLoading(true);
      setErrorMessage(null);
      const results: PromptWithServer[] = [];
      let failedCount = 0;

      const enabledServers = servers.filter((s) => s.enabled);
      const settled = await Promise.allSettled(
        enabledServers.map(async (server) => {
          const resp = await mcpAPI.getPrompts(server.id);
          return resp.prompts.map((p) => ({
            ...p,
            serverName: server.name,
            serverId: server.id,
          }));
        })
      );

      for (const result of settled) {
        if (result.status === 'fulfilled') {
          results.push(...result.value);
        } else {
          failedCount += 1;
        }
      }

      setAllPrompts(results);
      setErrorMessage(
        failedCount > 0 ? t('mcp.prompts.partialFailure', { count: failedCount }) : null
      );
      setIsLoading(false);
    };

    if (servers.length > 0) {
      void fetchPrompts();
    } else {
      queueMicrotask(() => {
        setIsLoading(false);
      });
    }
  }, [servers, t]);

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
      { label: t('mcp.prompts.allServers'), value: 'all' },
      ...servers.filter((s) => s.enabled).map((s) => ({ label: s.name, value: s.id })),
    ],
    [servers, t]
  );

  const serversWithPrompts = new Set(allPrompts.map((p) => p.serverId)).size;

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Spin size="large" />
        <p className="text-sm text-slate-400 mt-4">{t('mcp.prompts.loading')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-indigo-200 bg-indigo-50 dark:border-indigo-800 dark:bg-indigo-950/30">
                <MessageSquare size={20} className="text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {allPrompts.length}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('mcp.prompts.totalPrompts')}
                </p>
              </div>
            </div>
            <div className="w-px h-10 bg-slate-200 dark:bg-slate-700" />
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-200 bg-cyan-50 dark:border-cyan-800 dark:bg-cyan-950/30">
                <Server size={20} className="text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {serversWithPrompts}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('mcp.prompts.serversWithPrompts')}
                </p>
              </div>
            </div>
          </div>
          {filteredPrompts.length !== allPrompts.length && (
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {t('mcp.prompts.showCount', {
                shown: filteredPrompts.length,
                total: allPrompts.length,
              })}
            </span>
          )}
        </div>
      </div>

      {errorMessage && <Alert type="warning" showIcon title={errorMessage} />}

      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <AntSearch
              placeholder={t('mcp.prompts.searchPlaceholder')}
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
            placeholder={t('mcp.prompts.filterByServer')}
            options={serverOptions}
            suffix={<Server size={14} className="text-slate-400" />}
          />
        </div>
      </div>

      {filteredPrompts.length === 0 ? (
        <div
          className={`flex flex-col items-center justify-center py-16 text-center ${CARD_STYLES.base} border-dashed`}
        >
          <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-4">
            <MessageSquare size={28} className="text-slate-300 dark:text-slate-500" />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-1">
            {allPrompts.length === 0
              ? t('mcp.prompts.emptyNoPrompts')
              : t('mcp.prompts.emptyNoMatch')}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
            {allPrompts.length === 0 ? t('mcp.prompts.hintSync') : t('mcp.prompts.hintAdjust')}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredPrompts.map((prompt, idx) => {
            const key = `${prompt.serverId}-${prompt.name}-${idx.toString()}`;
            const isExpanded = expandedKey === key;
            const args = prompt.arguments ?? [];
            const hasArgs = args.length > 0;

            return (
              <div
                key={key}
                className={`${CARD_STYLES.base} overflow-hidden transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 hover:shadow-md`}
              >
                <button
                  type="button"
                  aria-expanded={isExpanded}
                  className="w-full p-4 flex items-start gap-3 text-left"
                  onClick={() => {
                    setExpandedKey(isExpanded ? null : key);
                  }}
                >
                  <div className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-indigo-200 bg-indigo-50 dark:border-indigo-800 dark:bg-indigo-950/30">
                    <MessageSquare size={16} className="text-indigo-600 dark:text-indigo-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white truncate">
                        {prompt.name}
                      </span>
                      {hasArgs && (
                        <Tag color="blue" className="text-xs">
                          {t('mcp.prompts.argCount', { count: args.length })}
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
                      {t('mcp.prompts.arguments')}
                    </p>
                    <div className="space-y-2">
                      {args.map((arg) => (
                        <div key={arg.name} className="flex items-start gap-2 text-sm">
                          <code className="text-xs font-mono bg-slate-200 dark:bg-slate-700 px-1.5 py-0.5 rounded text-slate-700 dark:text-slate-300">
                            {arg.name}
                          </code>
                          {arg.required && (
                            <span className="text-red-500 text-xs font-medium">
                              {t('mcp.prompts.required')}
                            </span>
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
