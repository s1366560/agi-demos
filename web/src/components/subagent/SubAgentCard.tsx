/**
 * SubAgentCard - Redesigned card for individual SubAgent display.
 * Shows trigger description, model badge, capabilities, performance metrics, and actions.
 */

import { memo, useCallback, useState } from 'react';

import { Popconfirm, Switch, Tooltip } from 'antd';
import {
  MoreHorizontal,
  Pencil,
  Trash2,
  Upload,
  Clock,
  Zap,
  TrendingUp,
  Hash,
  Wrench,
  Brain,
  Cable,
  RotateCw,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { SubAgentResponse } from '../../types/agent';

// Model color mapping
const MODEL_BADGE_STYLES: Record<string, string> = {
  'qwen-max': 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  'qwen-plus': 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  'qwen-turbo': 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  'gpt-4': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  'gpt-4-turbo': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  'gpt-3.5-turbo': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  'claude-3-opus': 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  'claude-3-sonnet': 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  'gemini-pro': 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  'deepseek-chat': 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
  inherit: 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
};

const getModelBadgeStyle = (model: string): string =>
  MODEL_BADGE_STYLES[model] || MODEL_BADGE_STYLES.inherit;

const formatTimeAgo = (dateStr: string | null | undefined): string => {
  if (!dateStr) return '-';
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 60000) return '<1m';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h`;
  return `${Math.floor(diff / 86400000)}d`;
};

interface SubAgentCardProps {
  subagent: SubAgentResponse;
  onToggle: (id: string, enabled: boolean) => void;
  onEdit: (subagent: SubAgentResponse) => void;
  onDelete: (id: string) => void;
  onExport?: (subagent: SubAgentResponse) => void;
}

export const SubAgentCard = memo<SubAgentCardProps>(
  ({ subagent, onToggle, onEdit, onDelete, onExport }) => {
    const { t } = useTranslation();
    const [menuOpen, setMenuOpen] = useState(false);

    const handleToggle = useCallback(
      (checked: boolean) => onToggle(subagent.id, checked),
      [subagent.id, onToggle],
    );

    const handleEdit = useCallback(() => {
      onEdit(subagent);
      setMenuOpen(false);
    }, [subagent, onEdit]);

    const handleExport = useCallback(() => {
      onExport?.(subagent);
      setMenuOpen(false);
    }, [subagent, onExport]);

    const toolCount = subagent.allowed_tools.includes('*')
      ? t('tenant.subagents.card.allTools', 'All')
      : String(subagent.allowed_tools.length);
    const skillCount = subagent.allowed_skills.length;
    const mcpCount = subagent.allowed_mcp_servers?.length ?? 0;

    return (
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 transition-colors overflow-hidden group">
        {/* Header */}
        <div className="p-4 pb-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-3 min-w-0">
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: (subagent.color || '#3B82F6') + '18' }}
              >
                <Hash size={18} style={{ color: subagent.color || '#3B82F6' }} />
              </div>
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                  {subagent.display_name}
                </h3>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-slate-400 dark:text-slate-500 truncate">
                    @{subagent.name}
                  </span>
                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${getModelBadgeStyle(subagent.model)}`}>
                    {subagent.model === 'inherit'
                      ? t('tenant.subagents.card.inherit', 'Inherit')
                      : subagent.model}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1.5 flex-shrink-0">
              <Switch checked={subagent.enabled} onChange={handleToggle} size="small" />
              {/* More menu */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setMenuOpen(!menuOpen)}
                  className="p-1 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                >
                  <MoreHorizontal size={16} />
                </button>
                {menuOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                    <div className="absolute right-0 top-full mt-1 w-44 bg-white dark:bg-slate-800 rounded-lg shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-20">
                      <button
                        type="button"
                        onClick={handleEdit}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
                      >
                        <Pencil size={14} className="text-slate-400" />
                        {t('common.edit', 'Edit')}
                      </button>
                      {onExport && (
                        <button
                          type="button"
                          onClick={handleExport}
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
                        >
                          <Upload size={14} className="text-slate-400" />
                          {t('tenant.subagents.card.exportTemplate', 'Export as Template')}
                        </button>
                      )}
                      <div className="border-t border-slate-100 dark:border-slate-700 my-1" />
                      <Popconfirm
                        title={t('tenant.subagents.card.deleteConfirm', 'Delete this SubAgent?')}
                        onConfirm={() => {
                          onDelete(subagent.id);
                          setMenuOpen(false);
                        }}
                        okText={t('common.delete', 'Delete')}
                        cancelText={t('common.cancel', 'Cancel')}
                        okButtonProps={{ danger: true }}
                      >
                        <button
                          type="button"
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                        >
                          <Trash2 size={14} />
                          {t('common.delete', 'Delete')}
                        </button>
                      </Popconfirm>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Trigger description */}
        <div className="px-4 pb-3">
          <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 leading-relaxed">
            {subagent.trigger.description || t('tenant.subagents.card.noDescription', 'No trigger description')}
          </p>
        </div>

        {/* Trigger keywords */}
        {subagent.trigger.keywords.length > 0 && (
          <div className="px-4 pb-3">
            <div className="flex flex-wrap gap-1">
              {subagent.trigger.keywords.slice(0, 4).map((kw) => (
                <span
                  key={kw}
                  className="px-1.5 py-0.5 text-[10px] bg-slate-100 dark:bg-slate-700/60 text-slate-500 dark:text-slate-400 rounded"
                >
                  {kw}
                </span>
              ))}
              {subagent.trigger.keywords.length > 4 && (
                <Tooltip title={subagent.trigger.keywords.slice(4).join(', ')}>
                  <span className="px-1.5 py-0.5 text-[10px] bg-slate-100 dark:bg-slate-700/60 text-slate-400 rounded cursor-help">
                    +{subagent.trigger.keywords.length - 4}
                  </span>
                </Tooltip>
              )}
            </div>
          </div>
        )}

        {/* Capabilities */}
        <div className="px-4 pb-3 flex items-center gap-3 text-[11px] text-slate-400 dark:text-slate-500">
          <span className="flex items-center gap-1">
            <Wrench size={11} /> {toolCount}
          </span>
          {skillCount > 0 && (
            <span className="flex items-center gap-1">
              <Brain size={11} /> {skillCount}
            </span>
          )}
          {mcpCount > 0 && (
            <span className="flex items-center gap-1">
              <Cable size={11} /> {mcpCount}
            </span>
          )}
          <span className="flex items-center gap-1">
            <RotateCw size={11} /> {subagent.max_iterations}
          </span>
        </div>

        {/* Performance footer */}
        <div className="px-4 py-2.5 bg-slate-50 dark:bg-slate-900/40 border-t border-slate-100 dark:border-slate-700/60 flex items-center justify-between text-[11px]">
          <div className="flex items-center gap-3 text-slate-500 dark:text-slate-400">
            <span className="flex items-center gap-1">
              <Zap size={11} />
              {subagent.total_invocations.toLocaleString()}
              {' '}{t('tenant.subagents.card.runs', 'runs')}
            </span>
            <span className="flex items-center gap-1">
              <TrendingUp size={11} />
              {Math.round(subagent.success_rate * 100)}%
            </span>
            {subagent.avg_execution_time_ms > 0 && (
              <span className="flex items-center gap-1">
                <Clock size={11} />
                {subagent.avg_execution_time_ms < 1000
                  ? `${Math.round(subagent.avg_execution_time_ms)}ms`
                  : `${(subagent.avg_execution_time_ms / 1000).toFixed(1)}s`}
              </span>
            )}
          </div>
          {subagent.updated_at && (
            <span className="text-slate-400 dark:text-slate-500">
              {formatTimeAgo(subagent.updated_at)}
            </span>
          )}
        </div>
      </div>
    );
  },
);

SubAgentCard.displayName = 'SubAgentCard';
