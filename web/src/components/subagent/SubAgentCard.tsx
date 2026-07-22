/**
 * SubAgentCard - Redesigned card for individual SubAgent display.
 * Shows trigger description, model badge, capabilities, performance metrics, and actions.
 */

import { memo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Dropdown, Switch, Tooltip } from 'antd';
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
  HardDrive,
  Database,
  Download,
} from 'lucide-react';

import { confirmAction } from '@/utils/confirmAction';
import { formatDistanceToNow } from '@/utils/date';

import type { SubAgentResponse } from '../../types/agent';
import type { MenuProps } from 'antd';

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
  MODEL_BADGE_STYLES[model] ??
  MODEL_BADGE_STYLES['inherit'] ??
  'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300';

const formatTimeAgo = (dateStr: string | null | undefined): string => {
  if (!dateStr) return '-';
  return formatDistanceToNow(dateStr) || '-';
};

interface SubAgentCardProps {
  subagent: SubAgentResponse;
  onToggle: (id: string, enabled: boolean) => void;
  onEdit: (subagent: SubAgentResponse) => void;
  onDelete: (id: string) => void;
  onExport?: ((subagent: SubAgentResponse) => void) | undefined;
  onImport?: ((name: string) => void) | undefined;
  getScopeLabel?: ((subagent: SubAgentResponse) => string) | undefined;
}

export const SubAgentCard = memo<SubAgentCardProps>(
  ({ subagent, onToggle, onEdit, onDelete, onExport, onImport, getScopeLabel }) => {
    const { t } = useTranslation();

    const isFilesystem = subagent.source === 'filesystem';
    const isReadonly = isFilesystem;

    const handleToggle = useCallback(
      (checked: boolean) => {
        onToggle(subagent.id, checked);
      },
      [subagent.id, onToggle]
    );

    const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
      if (key === 'edit') {
        onEdit(subagent);
      } else if (key === 'export') {
        onExport?.(subagent);
      } else if (key === 'import' && onImport) {
        onImport(subagent.name);
      } else if (key === 'delete') {
        void confirmAction({
          title: t('tenant.subagents.card.deleteConfirm', 'Delete this SubAgent?'),
          okText: t('common.delete', 'Delete'),
          cancelText: t('common.cancel', 'Cancel'),
          danger: true,
        }).then((confirmed) => {
          if (confirmed) onDelete(subagent.id);
        });
      }
    };

    const toolCount = subagent.allowed_tools.includes('*')
      ? t('tenant.subagents.card.allTools', 'All')
      : String(subagent.allowed_tools.length);
    const skillCount = subagent.allowed_skills.length;
    const mcpCount = subagent.allowed_mcp_servers.length;
    const scopeLabel =
      getScopeLabel?.(subagent) ??
      (subagent.project_id
        ? subagent.project_id
        : t('tenant.subagents.card.tenantScope', 'Tenant'));

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
                  <span
                    className={`inline-flex items-center px-1.5 py-0.5 rounded text-2xs font-medium ${getModelBadgeStyle(subagent.model)}`}
                  >
                    {subagent.model === 'inherit'
                      ? t('tenant.subagents.card.inherit', 'Inherit')
                      : subagent.model}
                  </span>
                  {isFilesystem ? (
                    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-2xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                      <HardDrive size={9} />
                      {t('tenant.subagents.card.filesystem', 'File')}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-2xs font-medium bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300">
                      <Database size={9} />
                      {t('tenant.subagents.card.database', 'DB')}
                    </span>
                  )}
                  <span className="inline-flex max-w-[108px] items-center truncate rounded bg-slate-100 px-1.5 py-0.5 text-2xs font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                    {scopeLabel}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1.5 flex-shrink-0">
              {!isReadonly && (
                <Switch
                  checked={subagent.enabled}
                  onChange={handleToggle}
                  size="small"
                  aria-label={t('tenant.subagents.card.toggle', {
                    name: subagent.display_name,
                    defaultValue: 'Toggle {{name}}',
                  })}
                />
              )}
              {/* More menu */}
              <Dropdown
                menu={{
                  items: isReadonly
                    ? [
                        ...(onImport
                          ? [
                              {
                                key: 'import',
                                icon: <Download size={14} />,
                                label: t('tenant.subagents.card.importToDb', 'Import to Database'),
                              },
                            ]
                          : []),
                        ...(subagent.file_path
                          ? [
                              {
                                key: 'path',
                                disabled: true,
                                label: (
                                  <Tooltip title={subagent.file_path}>
                                    <span className="text-xs-plus text-slate-400 dark:text-slate-500">
                                      {subagent.file_path}
                                    </span>
                                  </Tooltip>
                                ),
                              },
                            ]
                          : []),
                      ]
                    : [
                        {
                          key: 'edit',
                          icon: <Pencil size={14} />,
                          label: t('common.edit', 'Edit'),
                        },
                        ...(onExport
                          ? [
                              {
                                key: 'export',
                                icon: <Upload size={14} />,
                                label: t(
                                  'tenant.subagents.card.exportTemplate',
                                  'Export as Template'
                                ),
                              },
                            ]
                          : []),
                        { type: 'divider' as const },
                        {
                          key: 'delete',
                          icon: <Trash2 size={14} />,
                          label: t('common.delete', 'Delete'),
                          danger: true,
                        },
                      ],
                  onClick: handleMenuClick,
                }}
                trigger={['click']}
                placement="bottomRight"
              >
                <button
                  type="button"
                  aria-label={t('tenant.subagents.card.openActions', {
                    name: subagent.display_name,
                    defaultValue: 'Open actions for {{name}}',
                  })}
                  title={t('tenant.subagents.card.openActions', {
                    name: subagent.display_name,
                    defaultValue: 'Open actions for {{name}}',
                  })}
                  className="p-1 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                >
                  <MoreHorizontal size={16} />
                </button>
              </Dropdown>
            </div>
          </div>
        </div>

        {/* Trigger description */}
        <div className="px-4 pb-3">
          <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 leading-relaxed">
            {subagent.trigger.description ||
              t('tenant.subagents.card.noDescription', 'No trigger description')}
          </p>
        </div>

        {/* Trigger keywords */}
        {subagent.trigger.keywords.length > 0 && (
          <div className="px-4 pb-3">
            <div className="flex flex-wrap gap-1">
              {subagent.trigger.keywords.slice(0, 4).map((kw) => (
                <span
                  key={kw}
                  className="px-1.5 py-0.5 text-2xs bg-slate-100 dark:bg-slate-700/60 text-slate-500 dark:text-slate-400 rounded"
                >
                  {kw}
                </span>
              ))}
              {subagent.trigger.keywords.length > 4 && (
                <Tooltip title={subagent.trigger.keywords.slice(4).join(', ')}>
                  <span className="px-1.5 py-0.5 text-2xs bg-slate-100 dark:bg-slate-700/60 text-slate-400 rounded cursor-help">
                    +{subagent.trigger.keywords.length - 4}
                  </span>
                </Tooltip>
              )}
            </div>
          </div>
        )}

        {/* Capabilities */}
        <div className="px-4 pb-3 flex items-center gap-3 text-xs-plus text-slate-400 dark:text-slate-500">
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
        <div className="px-4 py-2.5 bg-slate-50 dark:bg-slate-900/40 border-t border-slate-100 dark:border-slate-700/60 flex items-center justify-between text-xs-plus">
          <div className="flex items-center gap-3 text-slate-500 dark:text-slate-400">
            <span className="flex items-center gap-1">
              <Zap size={11} />
              {subagent.total_invocations.toLocaleString()}{' '}
              {t('tenant.subagents.card.runs', 'runs')}
            </span>
            <span className="flex items-center gap-1">
              <TrendingUp size={11} />
              {Math.round(subagent.success_rate * 100)}%
            </span>
            {subagent.avg_execution_time_ms > 0 && (
              <span className="flex items-center gap-1">
                <Clock size={11} />
                {subagent.avg_execution_time_ms < 1000
                  ? `${Math.round(subagent.avg_execution_time_ms).toString()}ms`
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
  }
);

SubAgentCard.displayName = 'SubAgentCard';
