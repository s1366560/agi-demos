import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TraceChainView } from '../../../../components/agent/multiAgent/TraceChainView';

import type { UntracedRunDetailsDTO } from '../../../../types/multiAgent';

describe('TraceChainView', () => {
  it('labels untraced single-run fallback as run details', () => {
    const data: UntracedRunDetailsDTO = {
      trace_id: null,
      conversation_id: 'conv-1',
      total: 1,
      runs: [
        {
          run_id: 'run-1',
          conversation_id: 'conv-1',
          subagent_name: 'builtin:sisyphus',
          task: 'Reply with the exact text TRACE VERIFY',
          status: 'completed',
          created_at: '2026-04-08T08:48:52.615388+00:00',
          started_at: '2026-04-08T08:48:52.671498+00:00',
          ended_at: '2026-04-08T08:49:18.464419+00:00',
          summary: null,
          error: null,
          execution_time_ms: 1000,
          tokens_used: null,
          metadata: {},
          frozen_result_text: null,
          frozen_at: null,
          trace_id: null,
          parent_span_id: null,
        },
      ],
    };

    render(<TraceChainView data={data} />);

    expect(screen.getByText('Run details')).toBeInTheDocument();
    expect(screen.queryByText(/Trace:/)).not.toBeInTheDocument();
  });
});
