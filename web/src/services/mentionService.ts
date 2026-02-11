/**
 * Service for @-mention autocomplete search.
 *
 * Queries the enhanced search endpoint to find entities and episodes
 * matching the user's mention query within a project.
 */

import { apiFetch } from './client/urlUtils';

export interface MentionItem {
  id: string;
  name: string;
  type: 'entity' | 'memory' | 'episode';
  entityType?: string;
  summary?: string;
}

export const mentionService = {
  async search(query: string, projectId: string): Promise<MentionItem[]> {
    const res = await apiFetch.post('/search-enhanced/advanced', {
      query,
      project_id: projectId,
      limit: 10,
    });
    const data = await res.json();

    const items: MentionItem[] = [];

    if (data.entities) {
      for (const e of data.entities) {
        items.push({
          id: e.id || e.uuid || e.name,
          name: e.name,
          type: 'entity',
          entityType: e.entity_type || e.type,
          summary: e.summary || e.description,
        });
      }
    }

    if (data.episodes) {
      for (const ep of data.episodes) {
        items.push({
          id: ep.id || ep.uuid,
          name: ep.name || ep.title || ep.content?.slice(0, 40),
          type: 'memory',
          summary: ep.content?.slice(0, 80),
        });
      }
    }

    return items.slice(0, 10);
  },
};
