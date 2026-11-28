import { useEffect, useState } from 'react';
import { RunReviewDrawer } from '../../../../../web/src/components/agent/review/RunReviewDrawer';
import type { ActiveAgentRun } from '../../../../../web/src/services/runInputService';
import type { ReactNode } from 'react';
import { invoke } from './reviewAuthority';

export type RunProjection = Omit<ActiveAgentRun, 'run_id' | 'run_revision'> & {
  id: string;
  revision: number;
  started_at?: string;
  completed_at?: string;
  updated_at: string;
  permission_profile?: string;
  error?: string;
};
export function SelectedRunReview({
  conversation,
  busy,
  enabled,
  renderContext,
}: {
  conversation: string;
  busy: boolean;
  enabled: boolean;
  renderContext?: (run: RunProjection) => ReactNode;
}) {
  const [run, setRun] = useState<(ActiveAgentRun & RunProjection) | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    setError('');
    if (!conversation || !enabled) return;
    const controller = new AbortController();
    void invoke<{ latest_run: RunProjection | null }>(
      'review-latest',
      { conversation_id: conversation },
      { signal: controller.signal }
    )
      .then(({ latest_run: row }) => {
        if (!controller.signal.aborted)
          setRun(row ? { ...row, run_id: row.id, run_revision: row.revision } : null);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [conversation, busy, enabled]);
  if (error) return <span role="alert">{error}</span>;
  if (!enabled || !run || run.conversation_id !== conversation) return null;
  return (
    <>
      {renderContext?.(run)}
      <RunReviewDrawer key={run.run_id} run={run} latestTurnId={run.turn_id} />
    </>
  );
}
