import { render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useProjectConversationLoader } from '@/components/agent/useProjectConversationLoader';

type LoadConversations = (projectId: string) => Promise<void> | void;

function Harness({
  projectId,
  loadConversations,
}: {
  projectId?: string | null;
  loadConversations: LoadConversations;
}) {
  useProjectConversationLoader(projectId, loadConversations);
  return null;
}

describe('useProjectConversationLoader', () => {
  it('loads only when the project id changes, not when the action reference changes', async () => {
    const firstLoader = vi.fn<LoadConversations>();
    const secondLoader = vi.fn<LoadConversations>();

    const { rerender } = render(
      <Harness projectId="project-1" loadConversations={firstLoader} />
    );

    await waitFor(() => {
      expect(firstLoader).toHaveBeenCalledWith('project-1');
    });
    expect(firstLoader).toHaveBeenCalledTimes(1);

    rerender(<Harness projectId="project-1" loadConversations={secondLoader} />);

    await waitFor(() => {
      expect(firstLoader).toHaveBeenCalledTimes(1);
    });
    expect(secondLoader).not.toHaveBeenCalled();

    rerender(<Harness projectId="project-2" loadConversations={secondLoader} />);

    await waitFor(() => {
      expect(secondLoader).toHaveBeenCalledWith('project-2');
    });
    expect(secondLoader).toHaveBeenCalledTimes(1);
  });

  it('does not load without a project id', () => {
    const loadConversations = vi.fn<LoadConversations>();

    const { rerender } = render(
      <Harness projectId={null} loadConversations={loadConversations} />
    );
    rerender(<Harness projectId={undefined} loadConversations={loadConversations} />);

    expect(loadConversations).not.toHaveBeenCalled();
  });
});
