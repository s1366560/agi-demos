/**
 * Transcript pieces of a turn that sit between messages: the reasoning block, the
 * human-in-the-loop cards and the error notice. They are shared by the original
 * workbench transcript and by the signed chat page, which renders the same events
 * inside its isolated document.
 */

import { memo, useState, type FC } from "react";

import { useTranslation } from "react-i18next";

import { ChevronDown, ChevronUp, Lightbulb } from "lucide-react";

import { MessageTime } from "../../chat/MessageTime";
import { MESSAGE_MAX_WIDTH_CLASSES } from "@/components/agent/styles";
import { InlineHITLCard } from "@/components/agent/InlineHITLCard";

import type { ThoughtProps } from "./types";
import type {
  ClarificationAskedEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  PermissionAskedEventData,
  PermissionAskedTimelineEvent,
  PermissionRequestedTimelineEvent,
  TimelineEvent,
} from "@/types/agent";

// HITL Adapters - Convert TimelineEvent to SSE format for InlineHITLCard

/** Convert ClarificationAskedTimelineEvent to ClarificationAskedEventData (snake_case) */
export const toClarificationData = (
  event: TimelineEvent,
): ClarificationAskedEventData | undefined => {
  if (event.type !== "clarification_asked") return undefined;
  const e = event as TimelineEvent & {
    requestId: string;
    question: string;
    clarificationType: string;
    options: unknown[];
    allowCustom: boolean;
    context?: Record<string, unknown> | undefined;
  };
  return {
    request_id: e.requestId,
    question: e.question,
    clarification_type:
      e.clarificationType as ClarificationAskedEventData["clarification_type"],
    options: e.options as ClarificationAskedEventData["options"],
    allow_custom: e.allowCustom,
    context: e.context || {},
  };
};

/** Convert DecisionAskedTimelineEvent to DecisionAskedEventData (snake_case) */
export const toDecisionData = (
  event: TimelineEvent,
): DecisionAskedEventData | undefined => {
  if (event.type !== "decision_asked") return undefined;
  const e = event as TimelineEvent & {
    requestId: string;
    question: string;
    decisionType: string;
    options: unknown[];
    allowCustom?: boolean | undefined;
    context?: Record<string, unknown> | undefined;
    defaultOption?: string | undefined;
  };
  return {
    request_id: e.requestId,
    question: e.question,
    decision_type: e.decisionType as DecisionAskedEventData["decision_type"],
    options: e.options as DecisionAskedEventData["options"],
    allow_custom: e.allowCustom || false,
    context: e.context || {},
    default_option: e.defaultOption,
  };
};

/** Convert EnvVarRequestedTimelineEvent to EnvVarRequestedEventData (snake_case) */
export const toEnvVarData = (
  event: TimelineEvent,
): EnvVarRequestedEventData | undefined => {
  if (event.type !== "env_var_requested") return undefined;
  const e = event as TimelineEvent & {
    requestId: string;
    toolName: string;
    fields: EnvVarRequestedEventData["fields"];
    message?: string | undefined;
    context?: Record<string, unknown> | undefined;
  };
  return {
    request_id: e.requestId,
    tool_name: e.toolName,
    fields: e.fields,
    message: e.message,
    context: e.context,
  };
};

/**
 * Convert PermissionAskedTimelineEvent to PermissionAskedEventData (snake_case)
 * Supports both 'permission_asked' (SSE) and 'permission_requested' (DB) event types
 */
export const toPermissionData = (
  event: TimelineEvent,
): PermissionAskedEventData | undefined => {
  if (
    event.type !== "permission_asked" &&
    event.type !== "permission_requested"
  )
    return undefined;
  const e = event;
  if (event.type === "permission_asked") {
    const asked = e as PermissionAskedTimelineEvent;
    return {
      request_id: asked.requestId,
      tool_name: asked.toolName,
      permission_type: "ask",
      description: asked.description,
      risk_level: asked.riskLevel,
      context: asked.context,
    };
  } else {
    const requested = e as PermissionRequestedTimelineEvent;
    return {
      request_id: requested.requestId,
      tool_name: requested.resource || "unknown",
      permission_type: "ask",
      description: requested.reason || requested.action || "",
      risk_level: requested.riskLevel,
      context: requested.context,
    };
  }
};

export type PermissionRequestFields = TimelineEvent & {
  requestId?: string | undefined;
  expiresAt?: string | undefined;
  createdAt?: string | undefined;
  answered?: boolean | undefined;
  granted?: boolean | undefined;
};

/** A permission request of the transcript, answered or still waiting. */
export function PermissionRequestCard({
  event,
}: {
  event: PermissionRequestFields;
}) {
  const { t } = useTranslation();
  const permissionData = toPermissionData(event);
  const e = event;
  return (
    <InlineHITLCard
      hitlType="permission"
      requestId={e.requestId || permissionData?.request_id || ""}
      permissionData={permissionData}
      isAnswered={e.answered === true}
      answeredGranted={e.granted === true}
      answeredValue={
        e.granted !== undefined
          ? e.granted
            ? t("agent.messageBubble.granted", "Granted")
            : t("agent.messageBubble.denied", "Denied")
          : undefined
      }
      expiresAt={e.expiresAt}
      createdAt={e.createdAt || String(event.timestamp)}
    />
  );
}

/** The fields the cards and the error notice read from an event. */
export type InlineEventFields = TimelineEvent & {
  requestId?: string | undefined;
  expiresAt?: string | undefined;
  createdAt?: string | undefined;
  answered?: boolean | undefined;
  granted?: boolean | undefined;
  answer?: string | undefined;
  decision?: string | string[] | undefined;
  providedVariables?: string[] | undefined;
  variableNames?: string[] | undefined;
  message?: string | undefined;
};

/** A human-in-the-loop card or an error notice, as the event records it. */
export function InlineEvent({ event }: { event: InlineEventFields }) {
  const { t } = useTranslation();
  const e = event;
  const createdAt = e.createdAt || String(event.timestamp);
  const decision = Array.isArray(e.decision)
    ? e.decision.join(", ")
    : e.decision;
  switch (event.type) {
    case "permission_asked":
    case "permission_requested":
      return <PermissionRequestCard event={event} />;

    case "permission_replied":
    case "permission_granted":
      return (
        <InlineHITLCard
          hitlType="permission"
          requestId={e.requestId || ""}
          isAnswered={true}
          answeredGranted={e.granted === true}
          answeredValue={
            e.granted
              ? t("agent.messageBubble.granted", "Granted")
              : t("agent.messageBubble.denied", "Denied")
          }
          createdAt={createdAt}
        />
      );

    case "clarification_asked":
      return (
        <InlineHITLCard
          hitlType="clarification"
          requestId={
            e.requestId || toClarificationData(event)?.request_id || ""
          }
          clarificationData={toClarificationData(event)}
          isAnswered={e.answered === true}
          answeredValue={e.answer}
          expiresAt={e.expiresAt}
          createdAt={createdAt}
        />
      );

    case "clarification_answered":
      return (
        <InlineHITLCard
          hitlType="clarification"
          requestId={e.requestId || ""}
          isAnswered={true}
          answeredValue={e.answer}
          createdAt={createdAt}
        />
      );

    case "decision_asked":
      return (
        <InlineHITLCard
          hitlType="decision"
          requestId={e.requestId || toDecisionData(event)?.request_id || ""}
          decisionData={toDecisionData(event)}
          isAnswered={e.answered === true}
          answeredValue={decision}
          expiresAt={e.expiresAt}
          createdAt={createdAt}
        />
      );

    case "decision_answered":
      return (
        <InlineHITLCard
          hitlType="decision"
          requestId={e.requestId || ""}
          isAnswered={true}
          answeredValue={decision}
          createdAt={createdAt}
        />
      );

    case "env_var_requested": {
      // An answer names what was provided; the values themselves are never shown.
      const provided = e.providedVariables?.join(", ");
      return (
        <InlineHITLCard
          hitlType="env_var"
          requestId={e.requestId || toEnvVarData(event)?.request_id || ""}
          envVarData={toEnvVarData(event)}
          isAnswered={e.answered === true}
          answeredValue={provided}
          expiresAt={e.expiresAt}
          createdAt={createdAt}
        />
      );
    }

    case "env_var_provided":
      return (
        <InlineHITLCard
          hitlType="env_var"
          requestId={e.requestId || ""}
          isAnswered={true}
          answeredValue={e.variableNames?.join(", ")}
          createdAt={createdAt}
        />
      );

    case "error":
      return (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p className="font-medium">{t("agent.chat.errors.title")}</p>
          <p className="whitespace-pre-wrap break-words">{e.message}</p>
        </div>
      );

    default:
      return null;
  }
}

// Thought/Reasoning Component - Modern pill style
export const Thought: FC<ThoughtProps> = memo(({ content, timestamp }) => {
  const [expanded, setExpanded] = useState(true);
  const { t } = useTranslation();

  if (!content) return null;
  // Reasoning payloads often start with a blank line; whitespace-pre-wrap would
  // render it as a phantom gap between the header and the text.
  const reasoningText = content.trim();
  if (!reasoningText) return null;

  return (
    <div className="flex items-start gap-3 pb-1">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Lightbulb size={16} className="text-slate-500 dark:text-slate-400" />
      </div>
      <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
        <div className="bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/45 dark:border-slate-700/45 rounded-md overflow-hidden">
          <button
            type="button"
            onClick={() => {
              setExpanded(!expanded);
            }}
            aria-expanded={expanded}
            className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-slate-100/50 dark:hover:bg-slate-700/30 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
          >
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
              {t("agent.messageBubble.reasoning", "Reasoning")}
            </span>
            <MessageTime timestamp={timestamp} className="ml-auto" />
            {expanded ? (
              <ChevronUp size={14} className="text-slate-400" />
            ) : (
              <ChevronDown size={14} className="text-slate-400" />
            )}
          </button>
          {expanded && (
            <div className="px-4 pb-3 pt-0.5">
              <p className="text-xs leading-5 text-slate-500 dark:text-slate-400 whitespace-pre-wrap">
                {reasoningText}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
Thought.displayName = "MessageBubble.Thought";
