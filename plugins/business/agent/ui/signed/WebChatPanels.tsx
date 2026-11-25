import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { TaskList } from '../../../../../web/src/components/agent/TaskList';
import type { AgentTask } from '../../../../../web/src/types/agent';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import {
  CanvasTextEditor,
  CanvasWelcome,
  type EditableCanvasType,
} from '../web/canvas/CanvasWelcome';
import { InteractionPanel } from './InteractionPanel';
import { invoke } from './reviewAuthority';
import type { Chat } from './useChat';

export function SignedTaskList({
  conversation,
  active,
}: {
  conversation: string;
  active: boolean;
}) {
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [failure, setFailure] = useState('');
  useEffect(() => {
    setTasks([]);
    setFailure('');
    if (!conversation) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const result = await invoke<{ tasks: AgentTask[] }>(
          'chat-project-context',
          {
            view: 'tasks',
            conversation_id: conversation,
          },
          { signal: controller.signal }
        );
        if (!controller.signal.aborted) {
          setFailure('');
          setTasks(result.tasks);
        }
      } catch (error) {
        if (!controller.signal.aborted) setFailure(String(error));
      } finally {
        if (active && !controller.signal.aborted) timer = setTimeout(load, 1800);
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [conversation, active]);
  return failure ? <div role="alert">{failure}</div> : <TaskList tasks={tasks} />;
}

export type CanvasDraft = { type: EditableCanvasType; title: string; content: string };

export function SignedCanvas({
  chat,
  scope,
  draft,
  change,
}: {
  chat: Chat;
  scope: RichPageContext;
  draft: CanvasDraft | null;
  change: (draft: CanvasDraft) => void;
}) {
  if (draft)
    return (
      <CanvasTextEditor {...draft} onContentChange={(content) => change({ ...draft, content })} />
    );
  return (
    <InteractionPanel
      conversation={chat.selected}
      enabled={
        chat.selectedRow?.execution_target === 'cloud' &&
        scope.commands.includes('chat-interactions')
      }
      active={!!chat.run}
      desktop={false}
      section="canvas"
      emptyCanvas={
        <CanvasWelcome handleNew={(type, title) => change({ type, title, content: '' })} />
      }
    />
  );
}

export function LinkedPackagePanel({
  mode,
  workspace,
  report,
}: {
  mode: 'code' | 'collab';
  workspace: string | null;
  report: (error: unknown) => void;
}) {
  const { t } = useTranslation();
  const anchor = useRef<HTMLDivElement>(null);
  const callback = useRef(report);
  callback.current = report;
  useEffect(() => {
    if (!anchor.current) return;
    if (!window.memstack.anchorSlot) {
      callback.current('page_host_upgrade_required');
      return;
    }
    const search =
      mode === 'collab' && workspace ? '?' + new URLSearchParams({ workspaceId: workspace }) : '';
    return window.memstack.anchorSlot(mode + '@1', anchor.current, search, (reason) =>
      callback.current(reason)
    );
  }, [mode, workspace]);
  return (
    <div
      ref={anchor}
      className="h-full min-h-0 w-full"
      aria-label={
        mode === 'code'
          ? t('agent.layout.modes.code', 'Code')
          : t('agent.layout.modes.collab', 'Collab')
      }
    />
  );
}
