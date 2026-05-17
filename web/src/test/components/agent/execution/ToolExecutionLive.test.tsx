import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ToolExecutionLive } from '../../../../components/agent/execution/ToolExecutionLive';

describe('ToolExecutionLive', () => {
  it('renders a concrete running progress state for search tools', () => {
    render(
      <ToolExecutionLive
        toolName="memory_search"
        status="running"
        executionMode="semantic"
        toolInput={{ query: 'agent memory' }}
      />
    );

    expect(screen.getByText('Searching knowledge graph')).toBeInTheDocument();
    expect(
      screen.getByText('Finding relevant entities, memories, and relationships.')
    ).toBeInTheDocument();
    expect(screen.getByText('Input accepted')).toBeInTheDocument();
    expect(screen.getByText('semantic mode active')).toBeInTheDocument();
    expect(screen.getByText('Awaiting response')).toBeInTheDocument();
    expect(screen.getByText(/"query": "agent memory"/)).toBeInTheDocument();
  });

  it('shows partial result progress while a tool is still running', () => {
    render(
      <ToolExecutionLive
        toolName="web_search"
        status="running"
        executionMode="keyword"
        resultCount={3}
      />
    );

    expect(screen.getByText('Fetching web context')).toBeInTheDocument();
    expect(screen.getByText('3 partial results')).toBeInTheDocument();
  });

  it('keeps completed result summaries separate from running progress', () => {
    render(<ToolExecutionLive toolName="memory_search" status="completed" resultCount={5} />);

    expect(screen.getByText('Search completed')).toBeInTheDocument();
    expect(screen.getByText('5 results found')).toBeInTheDocument();
    expect(screen.queryByText('Input accepted')).not.toBeInTheDocument();
  });
});
