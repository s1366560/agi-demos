/**
 * McpToolsTabV2 - Tools Tab with Modern UI
 * Redesigned with elegant tool list and expandable details
 */

import React, { useEffect, useMemo, useState } from 'react';

import { Spin, Input, Select } from 'antd';
import { Search, Wrench, Server } from 'lucide-react';

import { useMCPStore } from '@/stores/mcp';
import { useProjectStore } from '@/stores/project';

import { McpToolItemV2 } from './McpToolItemV2';
import { CARD_STYLES } from './styles';

import type { ToolWithServer } from './McpToolItemV2';

const { Search: AntSearch } = Input;

export const McpToolsTabV2: React.FC = () => {
  const [search, setSearch] = useState('');
  const [serverFilter, setServerFilter] = useState<string>('all');
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const servers = useMCPStore((s) => s.servers);
  const isLoading = useMCPStore((s) => s.isLoading);
  const listServers = useMCPStore((s) => s.listServers);
  const currentProject = useProjectStore((s) => s.currentProject);

  // Ensure servers are loaded
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
      { label: '全部服务器', value: 'all' },
      ...servers.map((s) => ({ label: s.name, value: s.id })),
    ],
    [servers]
  );

  const serversWithTools = servers.filter((s) => s.discovered_tools?.length).length;

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Spin size="large" />
        <p className="text-sm text-slate-400 mt-4">加载工具中...</p>
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
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-50 to-purple-50 dark:from-violet-900/20 dark:to-purple-900/20 flex items-center justify-center">
                <Wrench size={20} className="text-violet-600 dark:text-violet-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {allTools.length}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">工具总数</p>
              </div>
            </div>
            <div className="w-px h-10 bg-slate-200 dark:bg-slate-700" />
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-50 to-cyan-50 dark:from-blue-900/20 dark:to-cyan-900/20 flex items-center justify-center">
                <Server size={20} className="text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {serversWithTools}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">有工具的服务器</p>
              </div>
            </div>
          </div>
          {filteredTools.length !== allTools.length && (
            <span className="text-sm text-slate-500 dark:text-slate-400">
              显示 {filteredTools.length} / {allTools.length}
            </span>
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <AntSearch
              placeholder="搜索工具名称或描述..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); }}
              allowClear
              prefix={<Search size={16} className="text-slate-400" />}
              className="w-full"
            />
          </div>
          <Select
            value={serverFilter}
            onChange={setServerFilter}
            className="w-full sm:w-52"
            placeholder="按服务器筛选"
            options={serverOptions}
            suffixIcon={<Server size={14} className="text-slate-400" />}
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
            {allTools.length === 0 ? '暂无工具' : '无匹配工具'}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
            {allTools.length === 0 ? '同步 MCP 服务器以发现可用工具' : '尝试调整搜索或筛选条件'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredTools.map((tool, idx) => {
            const key = `${tool.serverId}-${tool.name}-${idx}`;
            const isExpanded = expandedKey === key;

            return (
              <McpToolItemV2
                key={key}
                tool={tool}
                isExpanded={isExpanded}
                onToggle={() => { setExpandedKey(isExpanded ? null : key); }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
};
