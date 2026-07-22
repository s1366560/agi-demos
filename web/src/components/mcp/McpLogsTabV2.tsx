/**
 * McpLogsTabV2 - MCP Server Logs Tab (SEP-1865 P2-3)
 * Displays server logs with level filtering and auto-refresh
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Button, Empty, Select, Spin, Tag } from 'antd';
import { RefreshCw, Server, ScrollText } from 'lucide-react';

import { useMCPStore } from '@/stores/mcp';

import { mcpAPI } from '@/services/mcpService';

import { formatDateTimeFull } from '@/utils/date';

import { CARD_STYLES } from './styles';
import { useMcpProjectScope } from './useMcpProjectScope';

interface LogEntry {
  level: string;
  logger?: string;
  data?: unknown;
  timestamp?: string;
}

const LOG_LEVELS = [
  'debug',
  'info',
  'notice',
  'warning',
  'error',
  'critical',
  'alert',
  'emergency',
] as const;

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
  const { t } = useTranslation();
  const [selectedServer, setSelectedServer] = useState<string>('');
  const [logLevel, setLogLevel] = useState<string>('info');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSettingLevel, setIsSettingLevel] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const servers = useMCPStore((s) => s.servers);
  const listServers = useMCPStore((s) => s.listServers);
  const { projectId } = useMcpProjectScope();

  // Ensure servers are loaded
  useEffect(() => {
    void listServers(projectId ? { project_id: projectId } : {});
  }, [projectId, listServers]);

  useEffect(() => {
    if (selectedServer && !servers.some((server) => server.id === selectedServer)) {
      setSelectedServer('');
      setLogs([]);
    }
  }, [selectedServer, servers]);

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

  const logLevelOptions = useMemo(
    () => LOG_LEVELS.map((level) => ({ label: t(`mcp.logs.levels.${level}`), value: level })),
    [t]
  );

  const fetchLogs = useCallback(async () => {
    if (!selectedServer) return;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const resp = await mcpAPI.getLogs(selectedServer);
      setLogs(resp.logs);
    } catch {
      setLogs([]);
      setErrorMessage(t('mcp.logs.fetchFailed'));
    } finally {
      setIsLoading(false);
    }
  }, [selectedServer, t]);

  // Fetch logs when server changes
  useEffect(() => {
    if (selectedServer) {
      void fetchLogs();
    }
  }, [selectedServer, fetchLogs]);

  const handleSetLevel = async () => {
    if (!selectedServer) return;
    setIsSettingLevel(true);
    setErrorMessage(null);
    try {
      await mcpAPI.setLogLevel(selectedServer, logLevel);
      await fetchLogs();
    } catch {
      setErrorMessage(t('mcp.logs.setLevelFailed'));
    } finally {
      setIsSettingLevel(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30">
            <ScrollText size={20} className="text-amber-600 dark:text-amber-400" />
          </div>
          <div>
            <p className="text-lg font-bold text-slate-900 dark:text-white">
              {t('mcp.logs.title')}
            </p>
          </div>
        </div>
      </div>

      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col sm:flex-row gap-4 items-end">
          <div className="flex-1 min-w-0">
            <label
              htmlFor="mcp-logs-server"
              className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 block"
            >
              {t('mcp.logs.server')}
            </label>
            <Select
              id="mcp-logs-server"
              value={selectedServer || null}
              onChange={setSelectedServer}
              className="w-full"
              placeholder={t('mcp.logs.selectServer')}
              options={serverOptions}
              suffix={<Server size={14} className="text-slate-400" />}
            />
          </div>
          <div className="w-40">
            <label
              htmlFor="mcp-logs-level"
              className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 block"
            >
              {t('mcp.logs.logLevel')}
            </label>
            <Select
              id="mcp-logs-level"
              value={logLevel}
              onChange={setLogLevel}
              className="w-full"
              options={logLevelOptions}
            />
          </div>
          <Button
            size="middle"
            onClick={() => void handleSetLevel()}
            loading={isSettingLevel}
            disabled={!selectedServer}
          >
            {t('mcp.logs.setLevel')}
          </Button>
          <Button
            size="middle"
            icon={<RefreshCw size={14} />}
            onClick={() => void fetchLogs()}
            loading={isLoading}
            disabled={!selectedServer}
          >
            {t('mcp.logs.refresh')}
          </Button>
        </div>
      </div>

      {errorMessage && <Alert type="error" showIcon title={errorMessage} />}

      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Spin size="large" />
          <p className="text-sm text-slate-400 mt-4">{t('mcp.logs.loading')}</p>
        </div>
      ) : logs.length === 0 ? (
        <div className={`${CARD_STYLES.base} p-8`}>
          <Empty
            description={selectedServer ? t('mcp.logs.emptySelected') : t('mcp.logs.emptyNoServer')}
          />
        </div>
      ) : (
        <div className={`${CARD_STYLES.base} overflow-hidden`}>
          <div className="max-h-[500px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/50 sticky top-0">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide w-24">
                    {t('mcp.logs.level')}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide w-40">
                    {t('mcp.logs.logger')}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                    {t('mcp.logs.data')}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide w-44">
                    {t('mcp.logs.time')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                {logs.map((log, idx) => (
                  <tr
                    key={`${log.timestamp ?? 'log'}-${idx.toString()}`}
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
                          : log.data === undefined
                            ? '-'
                            : JSON.stringify(log.data, null, 2)}
                      </pre>
                    </td>
                    <td className="px-4 py-2 text-xs tabular-nums text-slate-500 dark:text-slate-400">
                      {log.timestamp ? formatDateTimeFull(log.timestamp) : '-'}
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
