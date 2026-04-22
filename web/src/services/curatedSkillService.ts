/**
 * Curated Skills Library + Skill Submissions (P2-4).
 *
 * Thin API client over /api/v1/skills/curated, /api/v1/skills/{id}/submit,
 * and the admin submission-review endpoints.
 */

import { httpClient } from './client/httpClient';

export interface CuratedSkill {
  id: string;
  semver: string;
  revision_hash: string;
  source_skill_id: string | null;
  source_tenant_id: string | null;
  approved_by: string | null;
  approved_at: string | null;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface CuratedForkRequest {
  include_triggers?: boolean;
  include_executor?: boolean;
  include_metadata?: boolean;
  project_id?: string | null;
}

export type SubmissionStatus = 'pending' | 'approved' | 'rejected' | 'withdrawn';

export interface SkillSubmission {
  id: string;
  submitter_tenant_id: string;
  submitter_user_id: string | null;
  source_skill_id: string | null;
  proposed_semver: string;
  submission_note: string | null;
  status: SubmissionStatus | string;
  reviewer_id: string | null;
  review_note: string | null;
  reviewed_at: string | null;
  created_at: string;
  skill_snapshot: Record<string, unknown>;
}

export interface SkillSubmitPayload {
  proposed_semver: string;
  submission_note?: string | null;
}

export interface SubmissionEditPayload {
  proposed_semver?: string | null;
  submission_note?: string | null;
  refresh_snapshot?: boolean;
}

export type SemverBump = 'major' | 'minor' | 'patch';

export interface ReviewPayload {
  review_note?: string | null;
  bump?: SemverBump | null;
}

export const curatedSkillAPI = {
  list: (opts: { include_deprecated?: boolean } = {}) =>
    httpClient.get<CuratedSkill[]>('/skills/curated/', {
      params: { include_deprecated: opts.include_deprecated ?? false },
    }),

  fork: (id: string, body: CuratedForkRequest) =>
    httpClient.post<{ skill_id: string; parent_curated_id: string }>(
      `/skills/curated/${id}/fork`,
      body,
    ),

  submit: (skillId: string, body: SkillSubmitPayload) =>
    httpClient.post<SkillSubmission>(`/skills/${skillId}/submit`, body),

  listMySubmissions: () => httpClient.get<SkillSubmission[]>('/skills/submissions/mine'),

  editSubmission: (submissionId: string, body: SubmissionEditPayload) =>
    httpClient.patch<SkillSubmission>(`/skills/submissions/${submissionId}`, body),

  withdrawSubmission: (submissionId: string) =>
    httpClient.post<SkillSubmission>(`/skills/submissions/${submissionId}/withdraw`),

  adminList: (statusFilter: 'pending' | 'approved' | 'rejected' | 'withdrawn' = 'pending') =>
    httpClient.get<SkillSubmission[]>('/admin/skill-submissions/', {
      params: { status_filter: statusFilter },
    }),

  adminApprove: (submissionId: string, body: ReviewPayload = {}) =>
    httpClient.post<CuratedSkill>(
      `/admin/skill-submissions/${submissionId}/approve`,
      body,
    ),

  adminReject: (submissionId: string, body: ReviewPayload = {}) =>
    httpClient.post<SkillSubmission>(
      `/admin/skill-submissions/${submissionId}/reject`,
      body,
    ),
};

export default curatedSkillAPI;
