import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BrainCircuit, Loader2, MessageSquare, Wifi, Wrench } from 'lucide-react';
import { Tooltip } from 'antd';
import { ContextDetailPanel } from '../../../../../web/src/components/agent/context/ContextDetailPanel';
import { ContextStatusIndicator } from '../../../../../web/src/components/agent/context/ContextStatusIndicator';
import { useContextStore } from '../../../../../web/src/stores/contextStore';
import { AgentLifecycleControls, type ActorAction } from '../web/chat/AgentLifecycleControls';
import { AgentLifecycleBadge } from '../web/chat/AgentLifecycleBadge';
import type { ProjectAgentLifecycleState } from '../web/hooks/useUnifiedAgentStatus';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { invoke } from './reviewAuthority';

interface LifecycleSnapshot {
  lifecycle_state: ProjectAgentLifecycleState;
  tool_count: number;
  skill_count: number;
  allowed_actions?: ActorAction[];
  pool_managed?: boolean;
}

export function WebChatStatus({
  scope,
  conversation,
  count,
  running,
}: {
  scope: RichPageContext;
  conversation: string;
  count: number;
  running: boolean;
}) {
  const { t } = useTranslation();
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
