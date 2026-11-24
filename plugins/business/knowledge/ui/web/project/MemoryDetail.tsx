import { TaskList } from '@business/workspace/ui/web/components/tasks/TaskList';
import { subscribeToTask } from '@/hooks/useTaskSSE';
import { MemoryDetailView } from './MemoryDetailView';

export function MemoryDetail() {
  return <MemoryDetailView TaskList={TaskList} subscribeToTask={subscribeToTask} />;
}
