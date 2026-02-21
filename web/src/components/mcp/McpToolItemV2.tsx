/**
 * McpToolItemV2 - Modern MCP Tool List Item
 * Redesigned with elegant UI/UX, expandable details, and smooth animations
 */

import React from 'react';

import { Tag, Tooltip } from 'antd';
import {
  Wrench,
  ChevronDown,
  FileJson,
  Terminal,
  Wifi,
} from 'lucide-react';

import { SERVER_TYPE_STYLES, CARD_STYLES } from './styles';

import type { MCPToolInfo } from '@/types/agent';

export interface ToolWithServer extends MCPToolInfo {
  serverName: string;
  serverId: string;
  serverType: string;
}

export interface McpToolItemV2Props {
  tool: ToolWithServer;
  isExpanded: boolean;
  onToggle: () => void;
}

export const McpToolItemV2: React.FC<McpToolItemV2Props> = ({
  tool,
  isExpanded,
  onToggle,
}) => {
  const typeStyle = SERVER_TYPE_STYLES[tool.serverType] || SERVER_TYPE_STYLES.stdio;

  const ServerIcon = 
    tool.serverType === 'stdio' ? Terminal :
    tool.serverType === 'sse' ? Wifi :
    tool.serverType === 'websocket' ? Wifi :
    Terminal;

  return (
    <div
      className={`group ${CARD_STYLES.base} ${
        isExpanded
          ? 'shadow-lg shadow-primary-500/10 border-primary-200 dark:border-primary-800/50 ring-1 ring-primary-50 dark:ring-primary-900/20'
          : 'hover:shadow-md hover:border-slate-300 dark:hover:border-slate-600'
      } transition-all duration-300 overflow-hidden`}
    >
      {/* Header - Clickable */}
      <div
        className="p-4 cursor-pointer"
        onClick={onToggle}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            {/* Tool Icon */}
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 transition-colors ${
              isExpanded
                ? 'bg-gradient-to-br from-primary-50 to-primary-100 dark:from-primary-900/30 dark:to-primary-900/20 text-primary-600 dark:text-primary-400'
                : 'bg-slate-50 dark:bg-slate-700/50 text-slate-400 dark:text-slate-500'
            }`}>
              <Wrench size={18} />
            </div>

            {/* Tool Info */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                  {tool.name}
                </h4>
                {tool.input_schema && (
                  <Tooltip title="包含输入模式">
                    <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-slate-100 dark:bg-slate-700 text-slate-400 dark:text-slate-500">
                      <FileJson size={10} />
                    </span>
                  </Tooltip>
                )}
              </div>
              {tool.description ? (
                <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-1 mt-0.5">
                  {tool.description}
                </p>
              ) : (
                <p className="text-xs text-slate-400 dark:text-slate-500 italic mt-0.5">
                  暂无描述
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 flex-shrink-0">
            {/* Server Tag */}
            <Tag className="text-xs m-0 px-2.5 py-1 rounded-lg" color="default">
              <span className="flex items-center gap-1.5">
                <ServerIcon size={10} />
                {tool.serverName}
              </span>
            </Tag>

            {/* Expand Indicator */}
            <div className={`w-7 h-7 rounded-full flex items-center justify-center transition-all duration-300 ${
              isExpanded
                ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 rotate-180'
                : 'bg-slate-100 dark:bg-slate-700 text-slate-400 dark:text-slate-500'
            }`}>
              <ChevronDown size={14} />
            </div>
          </div>
        </div>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700/50 animate-in slide-in-from-top-2 duration-200">
          {/* Server Info */}
          <div className="flex items-center gap-4 py-3 text-xs text-slate-500 dark:text-slate-400">
            <div className="flex items-center gap-2">
              <div className={`w-6 h-6 rounded-lg flex items-center justify-center ${typeStyle.bg}`}>
                <ServerIcon size={12} className={typeStyle.text} />
              </div>
              <span className="font-medium text-slate-700 dark:text-slate-300">{tool.serverName}</span>
            </div>
            <span className="text-slate-300 dark:text-slate-600">•</span>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded ${typeStyle.bg} ${typeStyle.text}`}>
              <span className="material-symbols-outlined text-xs">{typeStyle.icon}</span>
              {tool.serverType.toUpperCase()}
            </span>
          </div>

          {/* Description */}
          {tool.description && (
            <div className="mb-4">
              <div className="flex items-center gap-1.5 mb-2">
                <FileJson size={12} className="text-slate-400" />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">功能说明</span>
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-400 leading-relaxed">
                {tool.description}
              </p>
            </div>
          )}

          {/* Input Schema */}
          {tool.input_schema && (
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <FileJson size={12} className="text-slate-400" />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">输入模式</span>
              </div>
              <pre className="p-3 bg-slate-50 dark:bg-slate-900/80 rounded-xl text-xs text-slate-700 dark:text-slate-300 overflow-auto max-h-80 border border-slate-100 dark:border-slate-800 font-mono">
                {JSON.stringify(tool.input_schema, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
