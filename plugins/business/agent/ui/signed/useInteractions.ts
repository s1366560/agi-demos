import { useCallback, useEffect, useRef, useState } from "react";
import type { InlineHITLCardProps } from "../web/hitl/InlineHITLCard";

export interface PendingRequest {
  id: string;
  request_type: "decision" | "permission" | "clarification" | "a2ui_action";
  question: string;
  options: NonNullable<InlineHITLCardProps["decisionData"]>["options"];
  created_at: string;
  expires_at?: string;
  block_id?: string;
  authority_revision: number;
  tool_name?: string;
  description?: string;
  allow_custom?: boolean;
  risk_level?: "low" | "medium" | "high";
  selection_mode?: "single" | "multiple";
  max_selections?: number;
}
export interface InteractionEvent {
  id: string;
  type: "canvas_updated" | "act" | "observe";
  execution_id?: string;
  toolName?: string;
  toolInput?: unknown;
  toolOutput?: string;
  isError?: boolean;
  action?: string;
  block_id?: string;
  block?: {
    id?: string;
    block_type?: string;
    title?: string;
    content?: string;
  };
}
type View = { events: InteractionEvent[]; requests: PendingRequest[] };
const empty: View = { events: [], requests: [] };
export function useInteractions(
  conversation: string,
  active: boolean,
  enabled: boolean,
) {
  const [data, setData] = useState<{ id: string; view: View }>();
  const [failure, setFailure] = useState("");
  const [refresh, setRefresh] = useState(0);
  const retryKeys = useRef(new Map<string, string>());
  useEffect(() => {
    if (!enabled || !conversation) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setFailure("");
    async function load() {
      try {
        const view = (await window.memstack.invoke(
          "chat-interactions",
          { conversation_id: conversation },
          { signal: controller.signal },
        )) as View;
        if (!controller.signal.aborted) setData({ id: conversation, view });
      } catch (cause) {
        if (!controller.signal.aborted) setFailure(String(cause));
      } finally {
        if (active && !controller.signal.aborted)
          timer = setTimeout(load, 1800);
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [conversation, active, enabled, refresh]);
  const respond = useCallback(
    async (request: PendingRequest, response: Record<string, unknown>) => {
      const key = JSON.stringify([
        conversation,
        request.id,
        request.authority_revision,
        response,
      ]);
      const id = retryKeys.current.get(key) ?? crypto.randomUUID();
      retryKeys.current.set(key, id);
      await window.memstack.invoke("chat-respond", {
        conversation_id: conversation,
        request_id: request.id,
        hitl_type: request.request_type,
        expected_revision: request.authority_revision,
        idempotency_key: id,
        response_data: response,
      });
      retryKeys.current.delete(key);
      setRefresh((v) => v + 1);
    },
    [conversation],
  );
  return {
    ...(data?.id === conversation && enabled ? data.view : empty),
    respond,
    failure,
  };
}
