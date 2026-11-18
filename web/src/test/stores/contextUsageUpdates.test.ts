import { expect, it } from 'vitest';

import { useContextStore } from '../../stores/contextStore';

it('keeps builder compression data while refreshing measured token usage', () => {
  const actions = useContextStore.getState();
  actions.reset();
  const distribution = { system: 5, user: 10, assistant: 11, tool: 12, summary: 13 };
  actions.handleContextStatus({
    source: 'context_builder',
    compression_level: 'l2_summarize',
    from_cache: true,
    messages_in_summary: 17,
    token_distribution: distribution,
  });
  actions.handleContextStatus({
    source: 'processor_usage',
    current_tokens: 24,
    token_budget: 120,
    occupancy_pct: 20,
    compression_level: 'none',
    from_cache: false,
    messages_in_summary: 0,
    token_distribution: {},
  });
  expect(useContextStore.getState().status).toMatchObject({
    currentTokens: 24,
    tokenBudget: 120,
    occupancyPct: 20,
    compressionLevel: 'l2_summarize',
    fromCache: true,
    messagesInSummary: 17,
    tokenDistribution: distribution,
  });
  actions.handleContextStatus({
    source: 'context_builder',
    compression_level: 'none',
    messages_in_summary: 0,
    from_cache: false,
  });
  expect(useContextStore.getState().status).toMatchObject({
    compressionLevel: 'none',
    messagesInSummary: 0,
    fromCache: false,
  });
  actions.reset();
});
