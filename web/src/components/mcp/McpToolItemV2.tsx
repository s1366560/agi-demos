/**
 * McpToolItemV2 - Modern MCP Tool List Item
 * Aligned with agent workspace design system
 */

import React from 'react';

import { Tag, Tooltip } from 'antd';
import { ChevronDown, FileJson } from 'lucide-react';

import { MaterialIcon } from '../agent/shared/MaterialIcon';

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
  const typeStyle = SERVER_TYPE_STYLES[tool.serverType as keyof typeof SERVER_TYPE_STYLES] || SERVER_TYPE_STYLES.stdio;

  return (
    <div
      className={`group ${CARD_STYLES.base} ${CARD_STYLES.hover} ${
        isExpanded
          ? 'border-primary bg-primary/5 dark:border-primary'
          : ''
      } transition-all duration-200 overflow-hidden`}
    >
      {/* Header - Clickable */}
      <div
        className="p-4 cursor-pointer"
        onClick={onToggle}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            {/* Tool Icon */}
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 transition-colors ${
              isExpanded
                ? 'bg-primary/10 text-primary'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-400'
            }`}>
              <MaterialIcon name="build" size={20} />
            </div>

            {/* Tool Info */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                  {tool.name}
                </h4>
                {tool.input_schema && (
                  <Tooltip title="Has input schema">
                    <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-slate-100 dark:bg-slate-800 text-slate-400">
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
                  No description
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 flex-shrink-0">
            {/* Server Tag */}
            <Tag className="text-xs m-0 px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 border-0">
              <span className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
                <MaterialIcon name={typeStyle.icon} size={12} />
                {tool.serverName}
              </span>
            </Tag>

            {/* Expand Indicator */}
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all duration-200 ${
              isExpanded
                ? 'bg-primary/10 text-primary rotate-180'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-400'
            }`}>
              <ChevronDown size={14} />
            </div>
          </div>
        </div>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-800">
          {/* Server Info */}
          <div className="flex items-center gap-4 py-3 text-xs text-slate-500 dark:text-slate-400">
            <div className="flex items-center gap-2">
              <div className={`w-6 h-6 rounded flex items-center justify-center ${typeStyle.bgColor}`}>
                <MaterialIcon name={typeStyle.icon} size={14} className={typeStyle.textColor} />
              </div>
              <span className="font-medium text-slate-700 dark:text-slate-300">{tool.serverName}</span>
            </div>
            <span className="text-slate-300 dark:text-slate-600">•</span>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${typeStyle.bgColor} ${typeStyle.textColor}`}>
              {tool.serverType.toUpperCase()}
            </span>
          </div>

          {/* Description */}
          {tool.description && (
            <div className="mb-4">
              <div className="flex items-center gap-1.5 mb-2">
                <FileJson size={12} className="text-slate-400" />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">Description</span>
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
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">Input Schema</span>
              </div>
              <pre className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg text-xs text-slate-700 dark:text-slate-300 overflow-auto max-h-80 border border-slate-200 dark:border-slate-700 font-mono">
                {JSON.stringify(tool.input_schema, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
