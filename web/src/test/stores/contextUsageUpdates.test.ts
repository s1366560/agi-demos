import { expect, it, vi } from 'vitest';

import { agentService } from '../../services/agentService';
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

it('restores the server checkpoint and clears it for a conversation without a summary', async () => {
  const actions = useContextStore.getState();
  const snapshot = {
    conversation_id: 'chat',
    message_count: 3,
    has_summary: true,
    compression_level: 'l2_summarize',
    summary_tokens: 12,
    messages_in_summary: 2,
    from_cache: true,
    messages_covered_up_to: 1000000,
    summary_schema_version: 'v1',
  };
  const fetch = vi.spyOn(agentService, 'getContextStatus').mockResolvedValue(snapshot);
  try {
    actions.reset();
    await actions.fetchContextStatus('chat', 'project');
    expect(useContextStore.getState().status).toMatchObject({
      summaryThroughUs: 1000000,
      summarySchemaVersion: 'v1',
    });
    fetch.mockResolvedValue({ ...snapshot, has_summary: false, from_cache: false });
    await actions.fetchContextStatus('chat', 'project');
    expect(useContextStore.getState().status).toMatchObject({
      summaryThroughUs: null,
      summarySchemaVersion: null,
    });
  } finally {
    fetch.mockRestore();
    actions.reset();
  }
});
