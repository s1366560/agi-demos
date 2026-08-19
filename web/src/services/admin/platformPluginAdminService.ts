/**
 * Platform plugin admin service (I4): profile/row views and the cutover
 * gate for the plugin control plane.
 */

import { httpClient } from '@/services/client/httpClient';

import type { PlatformPluginSnapshotResponse } from '@/types/pluginSlots';

const BASE_URL = '/platform-plugins';

export interface ShadowCapabilityReadiness {
  capability: string;
  ready: boolean;
  total_count: number;
  equal_count: number;
  diff_count: number;
  distinct_scope_count: number;
  observed_event_count: number;
  required_event_count: number;
  last_occurred_at: string | null;
  reasons: string[];
}

export interface ShadowReadiness {
  ready: boolean;
  checked_at: string;
  capabilities: ShadowCapabilityReadiness[];
  reasons: string[];
}

export interface RollbackDrillReadiness {
  ready: boolean;
  checked_at: string;
  reasons: string[];
}

export interface CutoverApproval {
  capability: string;
  approved_by: string;
  approved_at: string;
  expires_at: string;
  evidence: Record<string, unknown>;
}

export interface CutoverReadiness {
  ready: boolean;
  checked_at: string;
  shadow: ShadowReadiness;
  rollback_drill: RollbackDrillReadiness;
  approval: CutoverApproval | null;
  operator_approved: boolean;
  reasons: string[];
}

export const platformPluginAdminService = {
  snapshot: () => httpClient.get<PlatformPluginSnapshotResponse>(`${BASE_URL}/snapshot`),
  cutoverReadiness: () => httpClient.get<CutoverReadiness>(`${BASE_URL}/cutover/readiness`),
  approveCutover: (validForSeconds = 7 * 24 * 60 * 60) =>
    httpClient.post<CutoverApproval>(`${BASE_URL}/cutover/approve`, {
      valid_for_seconds: validForSeconds,
    }),
  revokeCutover: () => httpClient.post(`${BASE_URL}/cutover/revoke`, {}),
};
