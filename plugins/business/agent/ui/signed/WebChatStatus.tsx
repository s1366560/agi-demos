import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BrainCircuit, Loader2, MessageSquare, Wifi, Wrench } from 'lucide-react';
import { Tooltip } from 'antd';
import { ContextDetailPanel } from '../../../../../web/src/components/agent/context/ContextDetailPanel';
import { ContextStatusIndicator } from '../../../../../web/src/components/agent/context/ContextStatusIndicator';
import { deriveTaskProgress } from '../../../../../web/src/components/agent/tasks/taskProgressDerivation';
import { useContextStore } from '../../../../../web/src/stores/contextStore';
import type { AgentTask } from '../../../../../web/src/types/agent';
import { AgentLifecycleControls, type ActorAction } from '../web/chat/AgentLifecycleControls';
import { AgentLifecycleBadge } from '../web/chat/AgentLifecycleBadge';
import type { ProjectAgentLifecycleState } from '../web/hooks/useUnifiedAgentStatus';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { invoke } from './reviewAuthority';
import { sandboxConnection, type ProjectSandbox, type SandboxConnection } from './sandboxStatus';

interface LifecycleSnapshot {
  lifecycle_state: ProjectAgentLifecycleState;
  tool_count: number;
  skill_count: number;
  allowed_actions?: ActorAction[];
  pool_managed?: boolean;
}

const TONE_DOT = {
  idle: 'bg-slate-300 dark:bg-slate-600',
  ok: 'bg-emerald-500',
  running: 'bg-sky-500 animate-pulse motion-reduce:animate-none',
  warning: 'bg-amber-500',
  error: 'bg-rose-500',
} as const;

/** One status of the work in the conversation, as the original workbench shows it. */
function StatusSlot({
  label,
  value,
  tone,
  hint,
  progressPercent,
}: {
  label: string;
  value: string;
  tone: keyof typeof TONE_DOT;
  hint?: string;
  progressPercent?: number;
}) {
  return (
    <div
      className="flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-xs text-blue-800 dark:text-slate-200"
      title={hint ?? `${label}: ${value}`}
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${TONE_DOT[tone]}`} />
      <span className="text-[var(--color-text-muted)] dark:text-slate-400">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
      {typeof progressPercent === 'number' && (
        <span
          aria-hidden="true"
          className="ml-1 h-1.5 w-16 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
        >
          <span
            className="block h-full rounded-full bg-emerald-500 transition-[width] duration-300 motion-reduce:transition-none"
            style={{ width: `${String(progressPercent)}%` }}
          />
        </span>
      )}
    </div>
  );
}

export function WebChatStatus({
  scope,
  conversation,
  count,
  tasks,
  sandbox,
  tool,
  running,
}: {
  scope: RichPageContext;
  conversation: string;
  /** Rows of the conversation timeline that are loaded. */
  count: number;
  tasks: readonly AgentTask[];
  /** The sandbox of the project, as the context command last read it. */
  sandbox: ProjectSandbox | null | undefined;
  /** The sandbox tool that is running, if one is. */
  tool: string | undefined;
  running: boolean;
}) {
  const { t } = useTranslation();
  // A state the original workbench does not name leaves the slot as it was.
  const connection = useRef<SandboxConnection>('idle');
  const named = sandboxConnection(sandbox);
  if (named) connection.current = named;
  const taskProgress = deriveTaskProgress(tasks, running);
  const taskPercent =
    taskProgress.total > 0 ? Math.round((taskProgress.current / taskProgress.total) * 100) : 0;
  const [snapshot, setSnapshot] = useState<LifecycleSnapshot | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [pending, setPending] = useState(false);
  const [controlError, setControlError] = useState('');
  async function control(action: ActorAction) {
    if (pending || !snapshot?.allowed_actions?.includes(action)) return;
    setPending(true);
    setControlError('');
    try {
      await invoke('chat-lifecycle-control', { action });
    } catch (error) {
      setControlError(String(error));
    } finally {
      setSnapshot((current) => (current ? { ...current, allowed_actions: [] } : current));
      setPending(false);
      setRefreshIndex((value) => value + 1);
    }
  }
  const [failure, setFailure] = useState('');
  useEffect(() => {
    if (!scope.commands.includes('chat-project-context')) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const row = await invoke<LifecycleSnapshot>(
          'chat-project-context',
          { view: 'lifecycle' },
          { signal: controller.signal }
        );
        if (!controller.signal.aborted) {
          setSnapshot(row);
          setFailure('');
        }
      } catch (error) {
        if (!controller.signal.aborted) setFailure(String(error));
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, running ? 3000 : 30000);
      }
    }
    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [scope, running, refreshIndex]);
  useEffect(() => {
    const context = useContextStore.getState();
    context.reset();
    if (!conversation || !scope.projectId || !scope.commands.includes('chat-project-context'))
      return;
    let live = true;
    void context
      .fetchContextStatus(conversation, scope.projectId, () => live)
      .catch((error) => {
        if (live) setFailure(String(error));
      });
    return () => {
      live = false;
    };
  }, [conversation, scope, running]);

  return (
    <div className="px-4 py-1.5 flex items-center justify-between gap-2 min-w-0">
      <div className="flex items-center gap-2 min-w-0 overflow-hidden">
        {taskProgress.hasTasks && (
          <StatusSlot
            label={t('agent.statusBar.slots.task', 'Task')}
            value={`${String(taskProgress.current)}/${String(taskProgress.total)} · ${String(taskPercent)}%`}
            tone={
              taskProgress.status === 'failed'
                ? 'error'
                : taskProgress.status === 'completed'
                  ? 'ok'
                  : 'running'
            }
            hint={taskProgress.label ?? t('agent.statusBar.slots.taskProgress', 'Task progress')}
            progressPercent={taskPercent}
          />
        )}
        {running && (
          <StatusSlot
            label="LLM"
            value={t('agent.statusBar.slots.streaming', 'streaming')}
            tone="running"
          />
        )}
        {connection.current !== 'idle' && (
          <StatusSlot
            label="Sandbox"
            value={tool ? `${connection.current} · ${tool}` : connection.current}
            tone={
              connection.current === 'connected'
                ? 'ok'
                : connection.current === 'error'
                  ? 'error'
                  : 'running'
            }
          />
        )}
        {snapshot && <AgentLifecycleBadge lifecycle={snapshot.lifecycle_state} error={failure} />}
        {(failure || controlError) && (
          <span role="alert" className="truncate text-xs text-red-600">
            {failure || controlError}
          </span>
        )}
        {!!snapshot?.tool_count && (
          <span className="hidden sm:flex items-center gap-1 text-xs text-slate-500">
            <Wrench size={11} />
            {snapshot.tool_count}
          </span>
        )}
        {!!snapshot?.skill_count && (
          <span className="hidden sm:flex items-center gap-1 text-xs text-slate-500">
            <BrainCircuit size={11} />
            {snapshot.skill_count}
          </span>
        )}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
        <Tooltip title={t('agent.lifecycle.stats.messageCount')}>
          <div className="hidden sm:flex items-center gap-1 text-xs text-slate-500">
            <MessageSquare size={11} />
            <span>{count}</span>
          </div>
        </Tooltip>
        <ContextStatusIndicator />
        <ContextDetailPanel />
      </div>
      <div className="flex items-center gap-2 text-xs flex-shrink-0">
        {snapshot && scope.commands.includes('chat-lifecycle-control') && (
          <>
            <AgentLifecycleControls
              allowed={snapshot.allowed_actions ?? []}
              isActionPending={pending}
              poolManaged={snapshot.pool_managed ?? false}
              onAction={control}
            />
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
          </>
        )}
        {scope.commands.includes('chat-project-context') && !failure && (
          <div className="flex items-center gap-1.5 text-xs text-emerald-700 dark:text-emerald-400">
            {snapshot ? (
              <>
                <Wifi size={12} />
                <span>{t('agent.statusBar.connection.online', 'Online')}</span>
              </>
            ) : (
              <Loader2 size={12} className="animate-spin" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
