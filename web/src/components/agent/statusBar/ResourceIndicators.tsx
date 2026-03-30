import type { FC } from 'react';

import {
  Wrench,
  Plug,
  BrainCircuit,
  MessageSquare,
  ListTodo,
  Route,
  Filter,
  Zap,
} from 'lucide-react';

import type { UnifiedAgentStatus as AgentStatus } from '@/hooks/useUnifiedAgentStatus';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import { ContextStatusIndicator } from '../context/ContextStatusIndicator';

import type { TFunction } from 'i18next';

export interface ResourceIndicatorsProps {
  status: AgentStatus;
  messageCount: number;
  tasks: any[];
  hasInsights: boolean;
  executionPathDecision: any;
  selectionTrace: any;
  policyFiltered: any;
  domainLane: string | null;
  t: TFunction;
}

export const ResourceIndicators: FC<ResourceIndicatorsProps> = ({
  status,
  messageCount,
  tasks,
  hasInsights,
  executionPathDecision,
  selectionTrace,
  policyFiltered,
  domainLane,
  t,
}) => {
  return (
    <>
      {/* Resources: Tools with detailed breakdown */}
      {status.toolStats.total > 0 && (
        <>
          <div className="w-px h-3 bg-border-separator dark:bg-border-separator-dark hidden sm:block" />
          <LazyTooltip
            title={
              <div className="space-y-1">
                <div className="font-medium">{t('agent.lifecycle.stats.toolStats')}</div>
                <div>{t('agent.lifecycle.stats.totalTools')}: {status.toolStats.total}</div>
                <div>{t('agent.lifecycle.stats.builtinTools')}: {status.toolStats.builtin}</div>
                <div>{t('agent.lifecycle.stats.mcpTools')}: {status.toolStats.mcp}</div>
              </div>
            }
          >
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-text-muted">
              <Wrench size={11} />
              <span>{status.toolStats.builtin}</span>
              {status.toolStats.mcp > 0 && (
                <>
                  <span className="text-text-muted">+</span>
                  <Plug size={10} className="text-info" />
                  <span className="text-info">{status.toolStats.mcp}</span>
                </>
              )}
            </div>
          </LazyTooltip>
        </>
      )}

      {/* Resources: Skills with detailed breakdown */}
      {status.skillStats.total > 0 && (
        <>
          <div className="w-px h-3 bg-border-separator dark:bg-border-separator-dark hidden sm:block" />
          <LazyTooltip
            title={
              <div className="space-y-1">
                <div className="font-medium">{t('agent.lifecycle.stats.skillStats')}</div>
                <div>{t('agent.lifecycle.stats.totalSkills')}: {status.skillStats.total}</div>
                <div>{t('agent.lifecycle.stats.loaded')}: {status.skillStats.loaded}</div>
              </div>
            }
          >
            <div className="hidden sm:flex items-center gap-1 text-xs text-text-muted">
              <BrainCircuit size={11} />
              <span>
                {status.skillStats.loaded}/{status.skillStats.total}
              </span>
            </div>
          </LazyTooltip>
        </>
      )}

      {/* Message Count */}
      <div className="w-px h-3 bg-border-separator dark:bg-border-separator-dark hidden sm:block" />
      <LazyTooltip title={t('agent.lifecycle.stats.messageCount')}>
        <div className="hidden sm:flex items-center gap-1 text-xs text-text-muted">
          <MessageSquare size={11} />
          <span>{messageCount}</span>
        </div>
      </LazyTooltip>

      {/* Task Progress */}
      {tasks.length > 0 && (
        <>
          <div className="w-px h-3 bg-border-separator dark:bg-border-separator-dark hidden sm:block" />
          <LazyTooltip
            title={
              <div className="space-y-1">
                <div className="font-medium">{t('agent.lifecycle.stats.taskProgress')}</div>
                <div>
                  {t('agent.lifecycle.stats.completed')}: {tasks.filter((task) => task.status === 'completed').length}/{tasks.length}
                </div>
                <div>{t('agent.lifecycle.stats.inProgress')}: {tasks.filter((task) => task.status === 'in_progress').length}</div>
                <div>{t('agent.lifecycle.stats.pending')}: {tasks.filter((task) => task.status === 'pending').length}</div>
              </div>
            }
          >
            <div className="flex items-center gap-1 text-xs text-purple dark:text-purple-light">
              <ListTodo size={11} />
              <span className="tabular-nums">
                {tasks.filter((task) => task.status === 'completed').length}/{tasks.length}
              </span>
            </div>
          </LazyTooltip>
        </>
      )}

      {/* Context Window Status */}
      <div className="w-px h-3 bg-border-separator dark:bg-border-separator-dark hidden sm:block" />
      <div className="hidden sm:flex items-center">
        <ContextStatusIndicator />
      </div>

      {/* Plan Mode */}
      {status.planMode.isActive && (
        <>
          <div className="w-px h-3 bg-border-separator dark:bg-border-separator-dark hidden sm:block" />
          <LazyTooltip
            title={t('agent.lifecycle.planMode.tooltip', { mode: status.planMode.currentMode?.toUpperCase() || 'PLAN' })}
          >
            <div className="flex items-center gap-1 text-xs text-status-text-info dark:text-status-text-info-dark">
              <Zap size={11} />
              <span className="hidden sm:inline">
                {status.planMode.currentMode === 'plan' ? t('agent.lifecycle.planMode.label') : status.planMode.currentMode}
              </span>
            </div>
          </LazyTooltip>
        </>
      )}

      {/* Execution Insights */}
      {hasInsights && (
        <>
          <div className="w-px h-3 bg-border-separator dark:bg-border-separator-dark hidden sm:block" />
          <LazyTooltip
            title={
              <div className="space-y-2 max-w-xs">
                <div className="font-medium border-b border-border-light/20 pb-1">
                  Execution Insights
                </div>
                {executionPathDecision && (
                  <div className="flex items-start gap-2 text-xs">
                    <Route size={12} className="mt-0.5 text-status-text-info-dark flex-shrink-0" />
                    <div>
                      <span className="font-medium">Path:</span>{' '}
                      {executionPathDecision.path.replace(/_/g, ' ')} (
                      {executionPathDecision.confidence.toFixed(2)})
                      {domainLane && <span className="ml-1 opacity-70">· lane {domainLane}</span>}
                    </div>
                  </div>
                )}
                {selectionTrace && (
                  <div className="flex items-start gap-2 text-xs">
                    <Filter size={12} className="mt-0.5 text-purple-light flex-shrink-0" />
                    <div>
                      <span className="font-medium">Selection:</span> {selectionTrace.final_count}
                      /{selectionTrace.initial_count} tools kept across{' '}
                      {selectionTrace.stages.length} stages
                    </div>
                  </div>
                )}
                {policyFiltered && policyFiltered.removed_total > 0 && (
                  <div className="flex items-start gap-2 text-xs">
                    <Filter size={12} className="mt-0.5 text-status-text-warning-dark flex-shrink-0" />
                    <div>
                      <span className="font-medium">Policy:</span> filtered{' '}
                      {policyFiltered.removed_total} tools
                    </div>
                  </div>
                )}
              </div>
            }
          >
            <div className="flex items-center gap-1 text-xs text-text-muted hover:text-text-secondary dark:hover:text-text-inverse cursor-help transition-colors">
              <Route size={11} className="text-info" />
              <span className="hidden sm:inline">
                {executionPathDecision?.path.replace(/_/g, ' ') || 'Insights'}
              </span>
            </div>
          </LazyTooltip>
        </>
      )}
    </>
  );
};
