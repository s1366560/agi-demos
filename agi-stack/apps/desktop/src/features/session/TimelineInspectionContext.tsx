import {
  createContext,
  useCallback,
  useContext,
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
}: {
  children: ReactNode;
  sessionKey: string;
  isOpen?: boolean;
  onOpen: () => void;
  onOpenFile?: (path: string) => void;
}) {
  const [selections, setSelections] = useState<
    Readonly<Record<string, readonly AgentTimelineItem[]>>
  >({});
  const triggersRef = useRef(new Map<string, HTMLElement>());
  const sessionRef = useRef(sessionKey);
  sessionRef.current = sessionKey;
  const inspect = useCallback(
    (items: AgentTimelineItem[], trigger: HTMLElement) => {
      if (!items.length) return;
      triggersRef.current.set(sessionKey, trigger);
      setSelections((current) => ({ ...current, [sessionKey]: items }));
      onOpen();
    },
    [onOpen, sessionKey],
  );
  const dismiss = useCallback(() => {
    setSelections((current) => {
      const next = { ...current };
      delete next[sessionKey];
      return next;
    });
    const trigger = triggersRef.current.get(sessionKey);
    triggersRef.current.delete(sessionKey);
    window.requestAnimationFrame(() => {
      if (sessionRef.current === sessionKey && trigger?.isConnected) trigger.focus();
    });
  }, [sessionKey]);
  const value = useMemo(
    () => ({
      items: selections[sessionKey] ?? [],
      inspect,
      dismiss,
      onOpenFile,
    }),
    [selections, sessionKey, inspect, dismiss, onOpenFile],
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
