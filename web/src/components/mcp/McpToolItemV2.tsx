/**
 * McpToolItemV2 - Modern MCP Tool List Item
 * Aligned with agent workspace design system
 */

import React from 'react';

import { Tag, Tooltip } from 'antd';
import { ChevronDown, FileJson, Wrench ,
  CheckCircle,
  Square,
  StopCircle,
  Terminal,
  Cloud,
  Zap,
  Ban,
  Search,
  Sparkles,
  AlertTriangle,
  Activity,
  FlaskConical,
  RefreshCcw,
  Settings,
  Brain,
  Info,
  Loader2,
  AlertCircle,
  Globe,
  User
} from 'lucide-react';


import { SERVER_TYPE_STYLES, CARD_STYLES } from './styles';

import type { MCPToolInfo } from '@/types/agent';


const renderDynamicIcon = (name: string, size: number, className: string = '') => {
  switch (name) {
    case 'check_circle': return <CheckCircle size={size} className={className} />;
    case 'progress_activity': return <Loader2 size={size} className={`animate-spin ${className}`} />;
    case 'stop': return <Square size={size} className={className} />;
    case 'stop_circle': return <StopCircle size={size} className={className} />;
    case 'error': return <AlertCircle size={size} className={className} />;
    case 'warning': return <AlertTriangle size={size} className={className} />;
    case 'terminal': return <Terminal size={size} className={className} />;
    case 'http': return <Globe size={size} className={className} />;
    case 'cloud': return <Cloud size={size} className={className} />;
    case 'globe': return <Globe size={size} className={className} />;
    case 'zap': return <Zap size={size} className={className} />;
    case 'block': return <Ban size={size} className={className} />;
    case 'search': return <Search size={size} className={className} />;
    case 'person': return <User size={size} className={className} />;
    case 'auto_awesome': return <Sparkles size={size} className={className} />;
    case 'monitor_heart': return <Activity size={size} className={className} />;
    case 'refresh': return <RefreshCcw size={size} className={className} />;
    case 'sync': return <RefreshCcw size={size} className={className} />;
    case 'science': return <FlaskConical size={size} className={className} />;
    case 'settings': return <Settings size={size} className={className} />;
    case 'psychology': return <Brain size={size} className={className} />;
    case 'info': return <Info size={size} className={className} />;
    default: return <AlertCircle size={size} className={className} />;
  }
};

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

export const McpToolItemV2: React.FC<McpToolItemV2Props> = ({ tool, isExpanded, onToggle }) => {
  const typeStyle: (typeof SERVER_TYPE_STYLES)[keyof typeof SERVER_TYPE_STYLES] =
    (tool.serverType as keyof typeof SERVER_TYPE_STYLES) in SERVER_TYPE_STYLES
      ? SERVER_TYPE_STYLES[tool.serverType as keyof typeof SERVER_TYPE_STYLES]
      : SERVER_TYPE_STYLES.stdio;

  return (
    <div
      className={`group ${CARD_STYLES.base} ${CARD_STYLES.hover} ${
        isExpanded ? 'border-primary bg-primary/5 dark:border-primary' : ''
      } transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 overflow-hidden`}
    >
      {/* Header - Clickable */}
      <button
        type="button"
        className="w-full p-4 cursor-pointer text-left bg-transparent border-0"
        onClick={onToggle}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            {/* Tool Icon */}
            <div
              className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 transition-colors ${
                isExpanded
                  ? 'bg-primary/10 text-primary'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-400'
              }`}
            >
              <Wrench size={20} />
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
                {renderDynamicIcon(typeStyle.icon, 12, "")}
                {tool.serverName}
              </span>
            </Tag>

            {/* Expand Indicator */}
            <div
              className={`w-7 h-7 rounded-lg flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 ${
                isExpanded
                  ? 'bg-primary/10 text-primary rotate-180'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-400'
              }`}
            >
              <ChevronDown size={14} />
            </div>
          </div>
        </div>
      </button>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-800">
          {/* Server Info */}
          <div className="flex items-center gap-4 py-3 text-xs text-slate-500 dark:text-slate-400">
            <div className="flex items-center gap-2">
              <div
                className={`w-6 h-6 rounded flex items-center justify-center ${typeStyle.bgColor}`}
              >
                {renderDynamicIcon(typeStyle.icon, 14, typeStyle.textColor)}
              </div>
              <span className="font-medium text-slate-700 dark:text-slate-300">
                {tool.serverName}
              </span>
            </div>
            <span className="text-slate-300 dark:text-slate-600">•</span>
            <span
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${typeStyle.bgColor} ${typeStyle.textColor}`}
            >
              {tool.serverType.toUpperCase()}
            </span>
          </div>

          {/* Description */}
          {tool.description && (
            <div className="mb-4">
              <div className="flex items-center gap-1.5 mb-2">
                <FileJson size={12} className="text-slate-400" />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
                  Description
                </span>
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
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
                  Input Schema
                </span>
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
