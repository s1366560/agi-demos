import { useState, type ReactNode } from "react";
import { ClarificationForm } from "../desktop/chat/ClarificationForm";
import type { PendingRequest } from "./useInteractions";
import { useTranslation } from "react-i18next";
import { InlineHITLCard } from "../web/hitl/InlineHITLCard";
import { A2UISurfaceRenderer } from "../web/canvas/A2UISurfaceRenderer";
import { ToolResultDisplay } from "../web/chat/ToolResultDisplay";
import {
  ToolActivityList,
  type ToolActivity,
} from "../desktop/chat/ToolActivityList";
import { Answer } from "./ChatTranscriptView";
import {
  useInteractions,
  type InteractionEvent,
  type Interactions,
} from "./useInteractions";

function ToolMarkdown({ content }: { content: string }) {
  return <Answer text={content} />;
}

function projectedTools(events: InteractionEvent[]) {
  const tools = new Map<string, ToolActivity>();
  for (const event of events) {
    if (event.type !== "act" && event.type !== "observe") continue;
    const id = event.execution_id ?? event.id;
    const prev = tools.get(id);
    tools.set(id, {
      ...prev,
      id,
      toolName: event.toolName ?? prev?.toolName ?? "",
      status:
        event.type === "observe"
          ? event.isError
            ? "failed"
            : "completed"
          : "running",
      ...(event.toolInput !== undefined
        ? { input: JSON.stringify(event.toolInput, null, 2) }
        : {}),
      ...(event.toolOutput !== undefined
        ? {
            output:
              typeof event.toolOutput === "string"
                ? event.toolOutput
                : JSON.stringify(event.toolOutput, null, 2),
          }
        : {}),
    });
  }
  return [...tools.values()];
}
function DesktopClarification({
  request,
  respond,
}: {
  request: PendingRequest;
  respond(value: string): Promise<unknown>;
}) {
  const { t } = useTranslation();
  const [answer, setAnswer] = useState(""),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  return (
    <section className="timeline-details">
      <strong>{request.question}</strong>
      <ClarificationForm
        options={(request.options ?? []).map((o) => ({
          value: o.id,
          label: String(o.label ?? o.id),
        }))}
        disabled={busy}
        busy={busy}
        allowCustom={request.allow_custom ?? true}
        answer={answer}
        setAnswer={setAnswer}
        placeholder={t("agent.hitl.input.custom", "Your answer")}
        submitLabel={t("agent.hitl.button.submit", "Submit")}
        submit={(value) => {
          setBusy(true);
          setFailure("");
          void respond(value)
            .catch((error) => setFailure(String(error)))
            .finally(() => setBusy(false));
        }}
      />
      {failure && <p role="alert">{failure}</p>}
    </section>
  );
}
export function InteractionPanel({
  conversation,
  active,
  enabled,
  desktop,
  section = "all",
  emptyCanvas,
  emptyActivity,
  interactions,
  tools: listTools = true,
}: {
  conversation: string;
  active: boolean;
  enabled: boolean;
  desktop: boolean;
  section?: "all" | "canvas" | "activity";
  emptyCanvas?: ReactNode;
  emptyActivity?: ReactNode;
  /** Interactions the page already reads for its transcript, so the panel does not poll again. */
  interactions?: Interactions;
  /** Turn off once the page shows the tool steps inside the transcript itself. */
  tools?: boolean;
}) {
  const { t } = useTranslation();
  const own = useInteractions(conversation, active, enabled && !interactions);
  const { events, requests, respond, failure } = interactions ?? own;
  const tools = projectedTools(events);
  const blocks = new Map<string, NonNullable<InteractionEvent["block"]>>();
  for (const event of events) {
    if (event.type !== "canvas_updated" || !event.block_id) continue;
    if (event.action === "removed" || event.action === "deleted")
      blocks.delete(event.block_id);
    else if (event.block)
      blocks.set(event.block_id, {
        ...blocks.get(event.block_id),
        ...event.block,
      });
  }
  return (
    <>
      {failure && <div role="alert">{failure}</div>}
      {!failure && !events.length && !requests.length && emptyActivity}
      {section !== "canvas" && listTools && (desktop ? (
        <ToolActivityList
          items={tools}
          t={(key, params) =>
            t(key, {
              ...params,
              defaultValue: (
                {
                  "chat.callsCount": "Tool calls ({{count}})",
                  "chat.input": "Input",
                  "chat.output": "Output",
                  "chat.subagentStatus.completed": "Completed",
                  "chat.subagentStatus.failed": "Failed",
                  "chat.subagentStatus.running": "Running",
                } as Record<string, string>
              )[key],
            })
          }
        />
      ) : (
        tools.map((tool) => (
          <details
            key={tool.id}
            className="mb-2 rounded-lg border border-slate-200 px-3 py-2"
          >
            <summary>{tool.toolName}</summary>
            {tool.input && <pre>{tool.input}</pre>}
            {tool.output !== undefined && (
              <ToolResultDisplay
                result={tool.output}
                isError={tool.status === "failed"}
                MarkdownContent={ToolMarkdown}
              />
            )}
          </details>
        ))
      ))}
      {section === "canvas" && blocks.size === 0 && emptyCanvas}
      {section !== "activity" && [...blocks.entries()].map(([id, block]) => {
        const request = requests.find(
          (r) => r.request_type === "a2ui_action" && r.block_id === id,
        );
        return (
          <section key={id} aria-label={block.title}>
            <h3>{block.title}</h3>
            {block.block_type === "a2ui_surface" ? (
              <A2UISurfaceRenderer
                surfaceId={id}
                messages={block.content ?? ""}
                useAuthority={() => ({
                  conversationId: conversation,
                  hitlRequestId: request?.id,
                  respondToA2UIAction: async (_id, name, source, context) => {
                    if (!request) throw new Error("request_not_pending");
                    await respond(request, {
                      action_name: name,
                      source_component_id: source,
                      context,
                    });
                  },
                })}
              />
            ) : block.block_type === "markdown" ? (
              <Answer text={block.content ?? ""} />
            ) : (
              <pre>{block.content}</pre>
            )}
          </section>
        );
      })}
      {section !== "canvas" && requests
        .filter((r) => r.request_type !== "a2ui_action")
        .map((r) => {
          const type = r.request_type;
          if (type === "a2ui_action") return null;
          if (desktop && type === "clarification")
            return (
              <DesktopClarification
                key={r.id}
                request={r}
                respond={(answer) => respond(r, { answer })}
              />
            );
          const common = {
            request_id: r.id,
            question: r.question,
            context: {},
            options: r.options ?? [],
            allow_custom: r.allow_custom ?? true,
          };
          return (
            <InlineHITLCard
              key={r.id}
              hitlType={type}
              requestId={r.id}
              createdAt={r.created_at}
              expiresAt={r.expires_at}
              clarificationData={{ ...common, clarification_type: "custom" }}
              decisionData={{
                ...common,
                decision_type: "custom",
                selection_mode: r.selection_mode,
                max_selections: r.max_selections,
              }}
              permissionData={{
                request_id: r.id,
                tool_name: r.tool_name ?? "",
                description: r.description || r.question,
                permission_type: "ask",
                risk_level: r.risk_level,
              }}
              respondToClarification={(_id, answer) => respond(r, { answer })}
              respondToDecision={(_id, decision) => respond(r, { decision })}
              respondToPermission={(_id, granted) =>
                respond(r, {
                  granted,
                  action: granted ? "allow" : "deny",
                  scope: "once",
                })
              }
              respondToEnvVar={() =>
                Promise.reject(new Error("unsupported_request"))
              }
            />
          );
        })}
    </>
  );
}
