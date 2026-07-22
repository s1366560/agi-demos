/**
 * McpToolsTabV2 - Tools Tab with Modern UI
 * Redesigned with elegant tool list and expandable details
 */

import React, { useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Select, Spin } from 'antd';
import { Search, Server, Wrench } from 'lucide-react';

import { useMCPStore } from '@/stores/mcp';

import { McpToolItemV2 } from './McpToolItemV2';
import { CARD_STYLES } from './styles';
import { useMcpProjectScope } from './useMcpProjectScope';

import type { ToolWithServer } from './McpToolItemV2';

const { Search: AntSearch } = Input;

/** Cap rendered tool rows so large catalogs stay responsive. */
const TOOL_RENDER_CAP = 50;

export const McpToolsTabV2: React.FC = () => {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [serverFilter, setServerFilter] = useState<string>('all');
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const servers = useMCPStore((s) => s.servers);
  const isLoading = useMCPStore((s) => s.isLoading);
  const listServers = useMCPStore((s) => s.listServers);
  const { projectId } = useMcpProjectScope();

  // Ensure servers are loaded
  useEffect(() => {
    void listServers(projectId ? { project_id: projectId } : {});
  }, [projectId, listServers]);

  const allTools = useMemo<ToolWithServer[]>(
    () =>
      servers.flatMap((server) =>
        server.discovered_tools.map((tool) => ({
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
      { label: t('mcp.tools.allServers'), value: 'all' },
      ...servers.map((s) => ({ label: s.name, value: s.id })),
    ],
    [servers, t]
  );

  const serversWithTools = servers.filter((s) => s.discovered_tools.length > 0).length;

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Spin size="large" />
        <p className="text-sm text-slate-400 mt-4">{t('mcp.tools.loading')}</p>
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
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800">
                <Wrench size={20} className="text-violet-600 dark:text-violet-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {allTools.length}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('mcp.tools.totalTools')}
                </p>
              </div>
            </div>
            <div className="w-px h-10 bg-slate-200 dark:bg-slate-700" />
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800">
                <Server size={20} className="text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {serversWithTools}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('mcp.tools.serversWithTools')}
                </p>
              </div>
            </div>
          </div>
          {filteredTools.length !== allTools.length && (
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {t('mcp.tools.showCount', { shown: filteredTools.length, total: allTools.length })}
            </span>
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <AntSearch
              placeholder={t('mcp.tools.searchPlaceholder')}
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
            placeholder={t('mcp.tools.filterByServer')}
            aria-label={t('mcp.tools.filterByServer')}
            options={serverOptions}
            suffix={<Server size={14} className="text-slate-400" />}
          />
        </div>
      </div>

      {/* Tool List */}
      {filteredTools.length === 0 ? (
        <div
          className={`flex flex-col items-center justify-center py-16 text-center ${CARD_STYLES.base} border-dashed`}
        >
          <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-4">
            <Wrench size={28} className="text-slate-300 dark:text-slate-500" />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-1">
            {allTools.length === 0 ? t('mcp.tools.emptyNoTools') : t('mcp.tools.emptyNoMatch')}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
            {allTools.length === 0 ? t('mcp.tools.hintSync') : t('mcp.tools.hintAdjust')}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredTools.slice(0, TOOL_RENDER_CAP).map((tool, idx) => {
            const key = `${tool.serverId}-${tool.name}-${idx.toString()}`;
            const isExpanded = expandedKey === key;

            return (
              <McpToolItemV2
                key={key}
                tool={tool}
                isExpanded={isExpanded}
                onToggle={() => {
                  setExpandedKey(isExpanded ? null : key);
                }}
              />
            );
          })}
          {filteredTools.length > TOOL_RENDER_CAP && (
            <p className="pt-1 text-center text-xs text-slate-400 dark:text-slate-500">
              {t('mcp.tools.renderCapNote', {
                shown: TOOL_RENDER_CAP,
                total: filteredTools.length,
                defaultValue:
                  'Showing first {{shown}} of {{total}} tools — refine your search or server filter.',
              })}
            </p>
          )}
        </div>
      )}
    </div>
  );
};
