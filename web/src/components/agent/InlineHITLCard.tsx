import { memo } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';
import { InlineHITLCard as Card, type InlineHITLCardProps } from '@business/agent/ui/web/hitl/InlineHITLCard';
import { useUnifiedHITLStore } from '../../stores/hitlStore.unified';
export type { InlineHITLCardProps };
export const InlineHITLCard = memo((props: InlineHITLCardProps) => {
    // Unified HITL store for status tracking UI
    const { isSubmitting, submittingRequestId, requestStatus } = useUnifiedHITLStore(
      useShallow((state) => ({
        isSubmitting: state.isSubmitting,
        submittingRequestId: state.submittingRequestId,
        requestStatus: state.requestStatuses.get(props.requestId),
      }))
    );

    // AgentV3 store respond methods set up WebSocket handler + streaming state
    const { respondToClarification, respondToDecision, respondToEnvVar, respondToPermission } =
      useAgentV3Store(
        useShallow((state) => ({
          respondToClarification: state.respondToClarification,
          respondToDecision: state.respondToDecision,
          respondToEnvVar: state.respondToEnvVar,
          respondToPermission: state.respondToPermission,
        }))
      );


  return <Card {...props} submitting={isSubmitting && submittingRequestId === props.requestId}
    requestStatus={requestStatus}
    onAnswered={(id) => useUnifiedHITLStore.getState().updateRequestStatus(id, 'answered')}
    {...{respondToClarification, respondToDecision, respondToEnvVar, respondToPermission}} />;
});
export default InlineHITLCard;
