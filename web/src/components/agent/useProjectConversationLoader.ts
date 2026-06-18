import { useEffect, useRef } from 'react';

type LoadConversations = (projectId: string) => Promise<void> | void;

export function useProjectConversationLoader(
  projectId: string | null | undefined,
  loadConversations: LoadConversations
): void {
  const loadConversationsRef = useRef(loadConversations);

  useEffect(() => {
    loadConversationsRef.current = loadConversations;
  }, [loadConversations]);

  useEffect(() => {
    if (projectId) {
      void loadConversationsRef.current(projectId);
    }
  }, [projectId]);
}
