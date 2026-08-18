import type React from 'react';

import { useTranslation } from 'react-i18next';

import { SummaryTile } from '@/pages/tenant/WorkspaceSettingsPrimitives';

export interface SummarySectionProps {
  useCaseLabel: string;
  workspaceType: string;
  modeLabel: string;
  memberCount: number;
}

export const SummarySection: React.FC<SummarySectionProps> = ({
  useCaseLabel,
  workspaceType,
  modeLabel,
  memberCount,
}) => {
  const { t } = useTranslation();

  return (
    <section className="grid gap-3 md:grid-cols-4">
      <SummaryTile label={t('workspaceSettings.summary.useCase')} value={useCaseLabel} />
      <SummaryTile label={t('workspaceSettings.summary.type')} value={workspaceType} />
      <SummaryTile label={t('workspaceSettings.summary.mode')} value={modeLabel} />
      <SummaryTile label={t('workspaceSettings.summary.members')} value={String(memberCount)} />
    </section>
  );
};
