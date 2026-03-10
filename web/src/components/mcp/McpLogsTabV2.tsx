/**
 * McpLogsTabV2 - MCP Server Logs Tab (SEP-1865 P2-3)
 * Displays server logs with level filtering and auto-refresh
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { Spin, Select, Button, Empty, Tag } from 'antd';
import { RefreshCw, Server, ScrollText } from 'lucide-react';

import { useMCPStore } from '@/stores/mcp';
import { useProjectStore } from '@/stores/project';

import { mcpAPI } from '@/services/mcpService';

import { CARD_STYLES } from './styles';

interface LogEntry {
  level: string;
  logger?: string;
  data?: unknown;
  timestamp?: string;
}

const LOG_LEVELS = ['debug', 'info', 'notice', 'warning', 'error', 'critical', 'alert', 'emergency'] as const;

function getLevelColor(level: string): string {
  switch (level.toLowerCase()) {
    case 'debug':
      return 'default';
    case 'info':
      return 'blue';
    case 'notice':
      return 'cyan';
    case 'warning':
      return 'orange';
    case 'error':
      return 'red';
    case 'critical':
    case 'alert':
    case 'emergency':
      return 'volcano';
    default:
      return 'default';
  }
}

export const McpLogsTabV2: React.FC = () => {
  const [selectedServer, setSelectedServer] = useState<string>('');
  const [logLevel, setLogLevel] = useState<string>('info');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSettingLevel, setIsSettingLevel] = useState(false);

  const servers = useMCPStore((s) => s.servers);
  const listServers = useMCPStore((s) => s.listServers);
  const currentProject = useProjectStore((s) => s.currentProject);

  // Ensure servers are loaded
  useEffect(() => {
    if (servers.length === 0 && currentProject?.id) {
      listServers({ project_id: currentProject.id });
    }
  }, [servers.length, currentProject?.id, listServers]);

  // Auto-select first enabled server
  useEffect(() => {
    if (!selectedServer && servers.length > 0) {
      const enabled = servers.find((s) => s.enabled);
      if (enabled) setSelectedServer(enabled.id);
    }
  }, [servers, selectedServer]);

  const serverOptions = useMemo(
    () => servers.filter((s) => s.enabled).map((s) => ({ label: s.name, value: s.id })),
    [servers]
  );

  const fetchLogs = useCallback(async () => {
    if (!selectedServer) return;
    setIsLoading(true);
    try {
      const resp = await mcpAPI.getLogs(selectedServer);
      setLogs(resp.logs ?? []);
    } catch {
      setLogs([]);
    } finally {
      setIsLoading(false);
    }
  }, [selectedServer]);

  // Fetch logs when server changes
  useEffect(() => {
    if (selectedServer) {
      void fetchLogs();
    }
  }, [selectedServer, fetchLogs]);

  const handleSetLevel = async () => {
    if (!selectedServer) return;
    setIsSettingLevel(true);
    try {
      await mcpAPI.setLogLevel(selectedServer, logLevel);
    } catch {
      // silently handle
    } finally {
      setIsSettingLevel(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 flex items-center justify-center">
            <ScrollText size={20} className="text-amber-600 dark:text-amber-400" />
          </div>
          <div>
            <p className="text-lg font-bold text-slate-900 dark:text-white">Server Logs</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              View MCP server log messages (SEP-1865 logging)
            </p>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col sm:flex-row gap-4 items-end">
          <div className="flex-1 min-w-0">
            <label className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 block">
              Server
            </label>
            <Select
              value={selectedServer || undefined}
              onChange={setSelectedServer}
              className="w-full"
              placeholder="Select server"
              options={serverOptions}
              suffixIcon={<Server size={14} className="text-slate-400" />}
            />
          </div>
          <div className="w-40">
            <label className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 block">
              Log Level
            </label>
            <Select
              value={logLevel}
              onChange={setLogLevel}
              className="w-full"
              options={LOG_LEVELS.map((l) => ({ label: l, value: l }))}
            />
          </div>
          <Button
            size="middle"
            onClick={() => void handleSetLevel()}
            loading={isSettingLevel}
            disabled={!selectedServer}
          >
            Set Level
          </Button>
          <Button
            size="middle"
            icon={<RefreshCw size={14} />}
            onClick={() => void fetchLogs()}
            loading={isLoading}
            disabled={!selectedServer}
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* Logs */}
      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Spin size="large" />
          <p className="text-sm text-slate-400 mt-4">Loading logs...</p>
        </div>
      ) : logs.length === 0 ? (
        <div className={`${CARD_STYLES.base} p-8`}>
          <Empty
            description={
              selectedServer
                ? 'No log messages captured yet. Set a log level and interact with the server.'
                : 'Select a server to view logs.'
            }
          />
        </div>
      ) : (
        <div className={`${CARD_STYLES.base} overflow-hidden`}>
          <div className="max-h-[500px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/50 sticky top-0">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide w-24">
                    Level
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide w-40">
                    Logger
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                    Data
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide w-44">
                    Time
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                {logs.map((log, idx) => (
                  <tr
                    key={idx}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="px-4 py-2">
                      <Tag color={getLevelColor(log.level)} className="text-xs">
                        {log.level}
                      </Tag>
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-slate-600 dark:text-slate-400 truncate">
                      {log.logger ?? '-'}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-slate-700 dark:text-slate-300">
                      <pre className="whitespace-pre-wrap break-all max-w-xl">
                        {typeof log.data === 'string'
                          ? log.data
                          : JSON.stringify(log.data, null, 2) ?? '-'}
                      </pre>
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500 dark:text-slate-400">
                      {log.timestamp ?? '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
