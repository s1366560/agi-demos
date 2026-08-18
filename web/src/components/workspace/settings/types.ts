import type { WorkspaceDeliveryServiceConfig } from '@/types/workspace';

import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

export type UpdateDraft = <TKey extends keyof SettingsDraft>(
  key: TKey,
  value: SettingsDraft[TKey]
) => void;

export type UpdateDeliveryService = <TKey extends keyof WorkspaceDeliveryServiceConfig>(
  index: number,
  key: TKey,
  value: WorkspaceDeliveryServiceConfig[TKey]
) => void;
