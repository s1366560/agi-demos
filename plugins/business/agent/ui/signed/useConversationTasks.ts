import { useEffect, useState } from 'react';

import type { AgentTask } from '../../../../../web/src/types/agent';
import { invoke } from './reviewAuthority';

/**
 * The task list of a conversation. It is read again while a turn runs, for the
 * status bar and the task pane, which share this one reading.
 */
export function useConversationTasks(conversation: string, active: boolean, enabled: boolean) {
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [failure, setFailure] = useState('');
  useEffect(() => {
    setTasks([]);
    setFailure('');
    if (!conversation || !enabled) return;
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
  }, [conversation, active, enabled]);
  return { tasks, failure };
}
