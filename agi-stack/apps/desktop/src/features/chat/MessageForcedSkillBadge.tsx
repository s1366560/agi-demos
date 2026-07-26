import { LightningBoltIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { forcedSkillNameFromMessage } from './messageForcedSkillModel';
import type { StructuredMessageMetadata } from './messageForcedSkillModel';

export function MessageForcedSkillBadge({
  message,
}: {
  message: StructuredMessageMetadata;
}) {
  const { t } = useI18n();
  const skillName = forcedSkillNameFromMessage(message);
  if (!skillName) return null;

  return (
    <span
      className="forced-skill-message-badge"
      aria-label={t('chat.forcedSkillBadgeLabel', { skill: skillName })}
      title={skillName}
      data-testid="forced-skill-message-badge"
    >
      <LightningBoltIcon aria-hidden="true" />
      <span>{skillName}</span>
    </span>
  );
}
