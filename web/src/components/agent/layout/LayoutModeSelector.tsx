import { useShallow } from 'zustand/react/shallow';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { ChatLayoutSelector } from '@business/agent/ui/web/chat/ChatLayoutSelector';

export function LayoutModeSelector({ hasWorkspace = false }: { hasWorkspace?: boolean }) {
  const { mode, setMode } = useLayoutModeStore(
    useShallow((state) => ({ mode: state.mode, setMode: state.setMode }))
  );
  return <ChatLayoutSelector mode={mode} setMode={setMode} hasWorkspace={hasWorkspace} />;
}
