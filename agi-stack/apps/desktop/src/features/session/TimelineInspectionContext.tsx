import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { AgentTimelineItem } from "../../types";

type TimelineInspection = {
  items: readonly AgentTimelineItem[];
  inspect: (items: AgentTimelineItem[], trigger: HTMLElement) => void;
  dismiss: () => void;
  onOpenFile?: (path: string) => void;
};

const TimelineInspectionContext = createContext<TimelineInspection>({
  items: [],
  inspect: () => {},
  dismiss: () => {},
});

export function TimelineInspectionProvider({
  children,
  sessionKey,
  onOpen,
  onOpenFile,
  isOpen,
}: {
  children: ReactNode;
  sessionKey: string;
  isOpen?: boolean;
  onOpen: () => void;
  onOpenFile?: (path: string) => void;
}) {
  const [selection, setSelection] = useState<{
    sessionKey: string;
    items: readonly AgentTimelineItem[];
  } | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const inspect = useCallback(
    (items: AgentTimelineItem[], trigger: HTMLElement) => {
      if (!items.length) return;
      triggerRef.current = trigger;
      setSelection({ sessionKey, items });
      onOpen();
    },
    [onOpen, sessionKey],
  );
  const dismiss = useCallback(() => {
    setSelection(null);
    const trigger = triggerRef.current;
    triggerRef.current = null;
    window.requestAnimationFrame(() => {
      if (trigger?.isConnected) trigger.focus();
    });
  }, []);
  useEffect(() => {
    if (isOpen === false && selection?.sessionKey === sessionKey) dismiss();
  }, [isOpen, selection, sessionKey, dismiss]);
  const value = useMemo(
    () => ({
      items: selection?.sessionKey === sessionKey ? selection.items : [],
      inspect,
      dismiss,
      onOpenFile,
    }),
    [selection, sessionKey, inspect, dismiss, onOpenFile],
  );
  return (
    <TimelineInspectionContext.Provider value={value}>
      {children}
    </TimelineInspectionContext.Provider>
  );
}

export function useTimelineInspection(): TimelineInspection {
  return useContext(TimelineInspectionContext);
}
