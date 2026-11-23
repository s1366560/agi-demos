import { httpClient as api } from '@/services/client/httpClient';
import type { QueueDepth, RecentTask, StatusBreakdown, TaskStats } from '@/types/memory';

type RecentTasksApiResponse =
  | RecentTask[]
  | {
      tasks?: RecentTask[] | undefined;
      items?: RecentTask[] | undefined;
      results?: RecentTask[] | undefined;
      total?: number | undefined;
      limit?: number | undefined;
      offset?: number | undefined;
      has_more?: boolean | undefined;
    };

export interface RecentTasksResult {
  tasks: RecentTask[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

const normalizeRecentTasksResponse = (
  response: RecentTasksApiResponse,
  params: { limit?: number | undefined; offset?: number | undefined } = {}
): RecentTasksResult => {
  if (Array.isArray(response)) {
    const limit = params.limit ?? response.length;
    const offset = params.offset ?? 0;
    return {
      tasks: response,
      total: response.length,
      limit,
      offset,
      has_more: limit > 0 && response.length >= limit,
    };
  }
  const tasks = response.tasks ?? response.items ?? response.results ?? [];
  const total = response.total ?? tasks.length;
  const limit = response.limit ?? params.limit ?? tasks.length;
  const offset = response.offset ?? params.offset ?? 0;
  return {
    tasks,
    total,
    limit,
    offset,
    has_more: response.has_more ?? offset + tasks.length < total,
  };
};

export const taskAPI = {
  getStats: async (): Promise<TaskStats> => {
    return await api.get('/tasks/stats');
  },
  getQueueDepth: async (): Promise<QueueDepth[]> => {
    return await api.get('/tasks/queue-depth');
  },
  getRecentTasks: async (
    params: {
      limit?: number | undefined;
      offset?: number | undefined;
      status?: string | undefined;
      task_type?: string | undefined;
      entity_id?: string | undefined;
      entity_type?: string | undefined;
      search?: string | undefined;
    } = {}
  ): Promise<RecentTasksResult> => {
    const response = await api.get<RecentTasksApiResponse>('/tasks/recent', { params });
    return normalizeRecentTasksResponse(response, params);
  },
  getStatusBreakdown: async (): Promise<StatusBreakdown> => {
    return await api.get('/tasks/status-breakdown');
  },
  retryTask: async (taskId: string): Promise<unknown> => {
    return await api.post(`/tasks/${taskId}/retry`);
  },
  retryPendingTasks: async (
    params: {
      limit?: number | undefined;
      task_type?: string | undefined;
      include_failed?: boolean | undefined;
      include_stale_processing?: boolean | undefined;
      stale_after_minutes?: number | undefined;
    } = {}
  ): Promise<{ submitted: number; skipped: number; limit: number; task_ids: string[] }> => {
    return await api.post('/tasks/retry-pending', undefined, { params });
  },
  stopTask: async (taskId: string): Promise<unknown> => {
    return await api.post(`/tasks/${taskId}/stop`);
  },
};
