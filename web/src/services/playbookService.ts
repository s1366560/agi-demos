/**
 * Playbook Service - reflection loop API
 *
 * Read-only client for the per-project reflection loop endpoints
 * (PR-B). The reflection loop distills frequently observed friction
 * patterns into reusable "playbooks" and records every reflector
 * verdict to an audit log so the UI can render a lessons-learned
 * timeline.
 */

import { apiFetch } from './client/urlUtils';

export interface PlaybookTrigger {
  description: string;
  friction_kinds: string[];
  lane_transitions: [string, string][];
}

export interface PlaybookStep {
  order: number;
  instruction: string;
  rationale: string | null;
}

export interface Playbook {
  id: string;
  project_id: string;
  name: string;
  status: string;
  trigger: PlaybookTrigger;
  steps: PlaybookStep[];
  hit_count: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReflectionVerdict {
  id: string;
  project_id: string;
  action: 'create' | 'reinforce' | 'deprecate' | 'noop';
  playbook_id: string | null;
  rationale: string;
  proposed_payload: Record<string, unknown> | null;
  created_at: string;
}

interface PlaybooksResponse {
  items: Playbook[];
}

interface VerdictsResponse {
  items: ReflectionVerdict[];
}

const buildQuery = (limit?: number): string => {
  if (limit === undefined) return '';
  return `?limit=${encodeURIComponent(String(limit))}`;
};

export const playbookService = {
  listPlaybooks: async (
    projectId: string,
    limit?: number
  ): Promise<Playbook[]> => {
    const response = await apiFetch.get(
      `/projects/${projectId}/playbooks${buildQuery(limit)}`
    );
    const body = (await response.json()) as PlaybooksResponse;
    return body.items;
  },

  listReflectionVerdicts: async (
    projectId: string,
    limit?: number
  ): Promise<ReflectionVerdict[]> => {
    const response = await apiFetch.get(
      `/projects/${projectId}/reflection-verdicts${buildQuery(limit)}`
    );
    const body = (await response.json()) as VerdictsResponse;
    return body.items;
  },
};
