import { invoke } from './reviewAuthority';
import type {
  ProjectStats,
  RecentSkill,
  TrendingEntity,
} from '../../../../../web/src/services/projectStatsService';

// The signed invocation supplies tenant and project from the active installation.
export const projectStatsService = {
  getStats: (_project: string) => invoke<ProjectStats>('chat-project-context', { view: 'stats' }),
  async getTrending(_project: string, limit = 10) {
    const { entities } = await invoke<{ entities: TrendingEntity[] }>('chat-project-context', {
      view: 'trending',
      limit,
    });
    return entities;
  },
  async getRecentSkills(_project: string, limit = 5) {
    const { skills } = await invoke<{ skills: RecentSkill[] }>('chat-project-context', {
      view: 'recent-skills',
      limit,
    });
    return skills;
  },
};
