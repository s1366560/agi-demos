import { ConversationModePanel } from '@/components/agent/ConversationModePanel';
import { ConversationParticipantsPanel } from '@/components/agent/ConversationParticipantsPanel';
import { HITLCenterPanel } from '@/components/agent/HITLCenterPanel';
import { useTranslation } from 'react-i18next';

export function RosterControls({
  conversationId,
  projectId,
}: {
  conversationId: string;
  projectId: string;
}) {
  const { t } = useTranslation();
  return (
    <>
      <section data-testid={`roster-mode-${conversationId}`}>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
          {t('blackboard.rosters.section.mode', { defaultValue: 'Mode' })}
        </div>
        <ConversationModePanel conversationId={conversationId} projectId={projectId} />
      </section>
      <section data-testid={`roster-participants-${conversationId}`}>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
          {t('blackboard.rosters.section.participants', {
            defaultValue: 'Participants',
          })}
        </div>
        <ConversationParticipantsPanel conversationId={conversationId} />
      </section>
      <section data-testid={`roster-hitl-${conversationId}`}>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
          {t('blackboard.rosters.section.hitl', { defaultValue: 'HITL Center' })}
        </div>
        <HITLCenterPanel conversationId={conversationId} />
      </section>
    </>
  );
}
