/**
 * TimelineEventItem - Optimized single timeline event renderer
 *
 * Renders individual TimelineEvents in chronological order with
 * improved visual hierarchy and spacing.
 *
 * Features:
 * - Natural time rendering for each event (不分组)
 * - Tool status tracking with act/observe matching
 * - Human-in-the-loop (HITL) interaction support
 *
 * @module components/agent/TimelineEventItem
 */

import { memo, lazy, Suspense, useState } from "react";
import {
  UserMessage,
  AgentSection,
  ToolExecutionCardDisplay,
} from "./chat/MessageStream";
import { AssistantMessage } from "./chat/AssistantMessage";
import { ReasoningLogCard } from "./chat/MessageStream";
import { formatDistanceToNowCN, formatReadableTime } from "../../utils/date";
import type { 
  TimelineEvent, 
  ActEvent, 
  ObserveEvent,
  ClarificationAskedTimelineEvent,
  DecisionAskedTimelineEvent,
  EnvVarRequestedTimelineEvent,
  ClarificationOption,
  DecisionOption,
  EnvVarField,
} from "../../types/agent";
import { useAgentV3Store } from "../../stores/agentV3";

// Lazy load ReactMarkdown to reduce initial bundle size (bundle-dynamic-imports)
// Using dynamic import with a wrapper to handle type issues
const MarkdownRenderer = lazy(async () => {
  const { default: ReactMarkdown } = await import('react-markdown');
  const { default: remarkGfm } = await import('remark-gfm');

  // Create a wrapper component that uses the plugins
  const MarkdownWrapper = ({ children }: { children: string }) => (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>
      {children}
    </ReactMarkdown>
  );

  return { default: MarkdownWrapper };
});

/**
 * TimeBadge - Natural time display component
 * 自然时间标签组件
 */
function TimeBadge({ timestamp }: { timestamp: number }) {
  const naturalTime = formatDistanceToNowCN(timestamp);
  const readableTime = formatReadableTime(timestamp);
  
  return (
    <span 
      className="text-[10px] text-slate-400 dark:text-slate-500 select-none"
      title={new Date(timestamp).toLocaleString('zh-CN')}
    >
      {naturalTime} · {readableTime}
    </span>
  );
}

export interface TimelineEventItemProps {
  /** The timeline event to render */
  event: TimelineEvent;
  /** Whether currently streaming */
  isStreaming?: boolean;
  /** All timeline events (for looking ahead to find observe events) */
  allEvents?: TimelineEvent[];
}

/**
 * Find matching observe event for an act event
 */
function findMatchingObserve(
  actEvent: ActEvent,
  events: TimelineEvent[]
): ObserveEvent | undefined {
  const actIndex = events.indexOf(actEvent);

  for (let i = actIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (event.type !== "observe") continue;

    // Priority 1: Match by execution_id
    if (actEvent.execution_id && event.execution_id) {
      if (actEvent.execution_id === event.execution_id) {
        return event;
      }
      continue;
    }

    // Priority 2: Fallback to toolName matching
    if (event.toolName === actEvent.toolName) {
      return event;
    }
  }
  return undefined;
}

/**
 * Render thought event
 */
function ThoughtItem({
  event,
  isStreaming,
}: {
  event: TimelineEvent;
  isStreaming: boolean;
}) {
  if (event.type !== "thought") return null;

  return (
    <div className="flex flex-col gap-1">
      <AgentSection icon="psychology" opacity={!isStreaming}>
        <ReasoningLogCard
          steps={[event.content]}
          summary="Thinking..."
          completed={!isStreaming}
          expanded={isStreaming}
        />
      </AgentSection>
      <div className="pl-12">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render act (tool call) event
 * 工具调用事件渲染 - 带状态跟踪
 */
function ActItem({
  event,
  allEvents,
}: {
  event: TimelineEvent;
  allEvents?: TimelineEvent[];
}) {
  if (event.type !== "act") return null;

  const observeEvent = allEvents ? findMatchingObserve(event, allEvents) : undefined;
  const hasCompleted = !!observeEvent;

  const ToolCard = hasCompleted && observeEvent ? (
    <AgentSection
      icon="construction"
      iconBg="bg-slate-100 dark:bg-slate-800"
      opacity={true}
    >
      <ToolExecutionCardDisplay
        toolName={event.toolName}
        status={observeEvent.isError ? "error" : "success"}
        parameters={event.toolInput}
        result={observeEvent.isError ? undefined : observeEvent.toolOutput}
        error={observeEvent.isError ? observeEvent.toolOutput : undefined}
        duration={observeEvent.timestamp - event.timestamp}
        defaultExpanded={false}
      />
    </AgentSection>
  ) : (
    <AgentSection
      icon="construction"
      iconBg="bg-slate-100 dark:bg-slate-800"
    >
      <ToolExecutionCardDisplay
        toolName={event.toolName}
        status="running"
        parameters={event.toolInput}
        defaultExpanded={true}
      />
    </AgentSection>
  );

  return (
    <div className="flex flex-col gap-1">
      {ToolCard}
      <div className="pl-12">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render observe (tool result) event
 * 工具结果事件渲染 - 孤儿observe（无对应act）时显示
 */
function ObserveItem({
  event,
  allEvents,
}: {
  event: TimelineEvent;
  allEvents?: TimelineEvent[];
}) {
  if (event.type !== "observe") return null;

  const hasMatchingAct = allEvents
    ? allEvents.some((e) => {
        if (e.type !== "act") return false;
        if ((e as ActEvent).execution_id && event.execution_id) {
          return (e as ActEvent).execution_id === event.execution_id;
        }
        return e.toolName === event.toolName && e.timestamp < event.timestamp;
      })
    : false;

  if (hasMatchingAct) {
    return null;
  }

  return (
    <div className="flex flex-col gap-1">
      <AgentSection
        icon="construction"
        iconBg="bg-slate-100 dark:bg-slate-800"
        opacity={true}
      >
        <ToolExecutionCardDisplay
          toolName={event.toolName}
          status={event.isError ? "error" : "success"}
          result={event.toolOutput}
          error={event.isError ? event.toolOutput : undefined}
          defaultExpanded={false}
        />
      </AgentSection>
      <div className="pl-12">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render work_plan event
 */
function WorkPlanItem({ event }: { event: TimelineEvent }) {
  if (event.type !== "work_plan") return null;

  return (
    <div className="flex flex-col gap-1">
      <AgentSection icon="psychology">
        <ReasoningLogCard
          steps={event.steps.map((s) => s.description)}
          summary={`Work Plan: ${event.steps.length} steps`}
          completed={event.status === "completed"}
          expanded={event.status !== "completed"}
        />
      </AgentSection>
      <div className="pl-12">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render step_start event
 */
function StepStartItem({ event }: { event: TimelineEvent }) {
  if (event.type !== "step_start") return null;

  const stepDesc = event.stepDescription;
  if (!stepDesc || stepDesc.trim() === "") {
    return null;
  }

  const stepIndex = event.stepIndex;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3 my-3 opacity-70">
        <div className="w-7 h-7 rounded-full bg-amber-100 dark:bg-amber-500/10 flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-amber-600 text-xs">
            play_arrow
          </span>
        </div>
        <div className="flex-1 text-sm text-slate-600 dark:text-slate-400 pt-1">
          {stepIndex !== undefined ? `Step ${stepIndex}: ` : ""}
          {stepDesc}
        </div>
      </div>
      <div className="pl-10">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render text_delta event (typewriter effect)
 * Uses ReactMarkdown for consistent rendering with final message
 */
function TextDeltaItem({
  event,
}: {
  event: TimelineEvent;
}) {
  if (event.type !== "text_delta") return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3 my-4">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
          <span className="material-symbols-outlined text-primary text-lg">
            smart_toy
          </span>
        </div>
        <div
          className="flex-1 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-sm p-4 prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md leading-relaxed"
        >
          <Suspense fallback={<div className="text-slate-400">Loading...</div>}>
            <MarkdownRenderer>
              {event.content}
            </MarkdownRenderer>
          </Suspense>
        </div>
      </div>
      <div className="pl-11">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render text_end event as formal assistant message
 * This displays the final content after streaming completes
 */
function TextEndItem({
  event,
}: {
  event: TimelineEvent;
}) {
  if (event.type !== "text_end") return null;

  const fullText = event.fullText || '';
  if (!fullText || !fullText.trim()) return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3 my-4">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
          <span className="material-symbols-outlined text-primary text-lg">
            smart_toy
          </span>
        </div>
        <div
          className="flex-1 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-sm p-4 prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md leading-relaxed"
        >
          <Suspense fallback={<div className="text-slate-400">Loading...</div>}>
            <MarkdownRenderer>
              {fullText}
            </MarkdownRenderer>
          </Suspense>
        </div>
      </div>
      <div className="pl-11">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

// ============================================
// Human-in-the-Loop Event Components
// ============================================

/**
 * Option button component for HITL events
 */
function OptionButton({
  option,
  isSelected,
  isRecommended,
  onClick,
  disabled,
}: {
  option: { id: string; label: string; description?: string };
  isSelected?: boolean;
  isRecommended?: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        w-full text-left p-3 rounded-lg border transition-all
        ${isSelected
          ? "border-primary bg-primary/10 dark:bg-primary/20"
          : "border-slate-200 dark:border-slate-700 hover:border-primary/50 hover:bg-slate-50 dark:hover:bg-slate-800"
        }
        ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
      `}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-sm">{option.label}</span>
        {isRecommended && (
          <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
            推荐
          </span>
        )}
      </div>
      {option.description && (
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          {option.description}
        </p>
      )}
    </button>
  );
}

/**
 * Render clarification_asked event (inline in timeline)
 */
function ClarificationAskedItem({ event }: { event: ClarificationAskedTimelineEvent }) {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [customAnswer, setCustomAnswer] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { respondToClarification } = useAgentV3Store();
  const isAnswered = event.answered || false;

  const handleSubmit = async () => {
    const answer = selectedOption || customAnswer;
    if (!answer) return;

    setIsSubmitting(true);
    try {
      await respondToClarification(event.requestId, answer);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3 my-3">
        <div className="w-8 h-8 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-amber-600 dark:text-amber-400 text-lg">
            help_outline
          </span>
        </div>
        <div className="flex-1 bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-amber-700 dark:text-amber-400 uppercase tracking-wider">
              需要澄清
            </span>
            {isAnswered && (
              <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
                已回答
              </span>
            )}
          </div>
          <p className="text-sm text-slate-700 dark:text-slate-300 mb-3">
            {event.question}
          </p>

          {!isAnswered ? (
            <>
              <div className="space-y-2 mb-3">
                {event.options.map((option: ClarificationOption) => (
                  <OptionButton
                    key={option.id}
                    option={option}
                    isSelected={selectedOption === option.id}
                    isRecommended={option.recommended}
                    onClick={() => {
                      setSelectedOption(option.id);
                      setCustomAnswer("");
                    }}
                    disabled={isSubmitting}
                  />
                ))}
              </div>

              {event.allowCustom && (
                <div className="mb-3">
                  <input
                    type="text"
                    placeholder="或输入自定义答案..."
                    value={customAnswer}
                    onChange={(e) => {
                      setCustomAnswer(e.target.value);
                      setSelectedOption(null);
                    }}
                    disabled={isSubmitting}
                    className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              )}

              <button
                onClick={handleSubmit}
                disabled={isSubmitting || (!selectedOption && !customAnswer)}
                className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isSubmitting ? "提交中..." : "确认"}
              </button>
            </>
          ) : (
            <div className="text-sm text-slate-600 dark:text-slate-400 bg-white/50 dark:bg-slate-800/50 rounded-lg p-2">
              <span className="font-medium">已选择:</span> {event.answer}
            </div>
          )}
        </div>
      </div>
      <div className="pl-11">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render decision_asked event (inline in timeline)
 */
function DecisionAskedItem({ event }: { event: DecisionAskedTimelineEvent }) {
  const [selectedOption, setSelectedOption] = useState<string | null>(event.defaultOption || null);
  const [customDecision, setCustomDecision] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { respondToDecision } = useAgentV3Store();
  const isAnswered = event.answered || false;

  const handleSubmit = async () => {
    const decision = selectedOption || customDecision;
    if (!decision) return;

    setIsSubmitting(true);
    try {
      await respondToDecision(event.requestId, decision);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3 my-3">
        <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 text-lg">
            rule
          </span>
        </div>
        <div className="flex-1 bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-blue-700 dark:text-blue-400 uppercase tracking-wider">
              需要决策
            </span>
            {isAnswered && (
              <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
                已决定
              </span>
            )}
          </div>
          <p className="text-sm text-slate-700 dark:text-slate-300 mb-3">
            {event.question}
          </p>

          {!isAnswered ? (
            <>
              <div className="space-y-2 mb-3">
                {event.options.map((option: DecisionOption) => (
                  <OptionButton
                    key={option.id}
                    option={option}
                    isSelected={selectedOption === option.id}
                    isRecommended={option.recommended}
                    onClick={() => {
                      setSelectedOption(option.id);
                      setCustomDecision("");
                    }}
                    disabled={isSubmitting}
                  />
                ))}
              </div>

              {event.allowCustom && (
                <div className="mb-3">
                  <input
                    type="text"
                    placeholder="或输入自定义决策..."
                    value={customDecision}
                    onChange={(e) => {
                      setCustomDecision(e.target.value);
                      setSelectedOption(null);
                    }}
                    disabled={isSubmitting}
                    className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              )}

              <button
                onClick={handleSubmit}
                disabled={isSubmitting || (!selectedOption && !customDecision)}
                className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isSubmitting ? "提交中..." : "确认决策"}
              </button>
            </>
          ) : (
            <div className="text-sm text-slate-600 dark:text-slate-400 bg-white/50 dark:bg-slate-800/50 rounded-lg p-2">
              <span className="font-medium">已决定:</span> {event.decision}
            </div>
          )}
        </div>
      </div>
      <div className="pl-11">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render env_var_requested event (inline in timeline)
 */
function EnvVarRequestedItem({ event }: { event: EnvVarRequestedTimelineEvent }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { respondToEnvVar } = useAgentV3Store();
  const isAnswered = event.answered || false;

  const handleChange = (name: string, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async () => {
    // Check required fields
    const missingRequired = event.fields.filter(
      (f: EnvVarField) => f.required && !values[f.name]
    );
    if (missingRequired.length > 0) {
      return;
    }

    setIsSubmitting(true);
    try {
      await respondToEnvVar(event.requestId, values);
    } finally {
      setIsSubmitting(false);
    }
  };

  const requiredFilled = event.fields
    .filter((f: EnvVarField) => f.required)
    .every((f: EnvVarField) => values[f.name]);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3 my-3">
        <div className="w-8 h-8 rounded-full bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-purple-600 dark:text-purple-400 text-lg">
            key
          </span>
        </div>
        <div className="flex-1 bg-purple-50 dark:bg-purple-900/10 border border-purple-200 dark:border-purple-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-purple-700 dark:text-purple-400 uppercase tracking-wider">
              需要配置
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {event.toolName}
            </span>
            {isAnswered && (
              <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
                已提供
              </span>
            )}
          </div>
          {event.message && (
            <p className="text-sm text-slate-700 dark:text-slate-300 mb-3">
              {event.message}
            </p>
          )}

          {!isAnswered ? (
            <>
              <div className="space-y-3 mb-3">
                {event.fields.map((field: EnvVarField) => (
                  <div key={field.name}>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                      {field.label}
                      {field.required && (
                        <span className="text-red-500 ml-1">*</span>
                      )}
                    </label>
                    {field.description && (
                      <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
                        {field.description}
                      </p>
                    )}
                    {field.input_type === "textarea" ? (
                      <textarea
                        placeholder={field.placeholder || `请输入 ${field.label}`}
                        value={values[field.name] || field.default_value || ""}
                        onChange={(e) => handleChange(field.name, e.target.value)}
                        disabled={isSubmitting}
                        rows={3}
                        className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                      />
                    ) : (
                      <input
                        type={field.input_type === "password" ? "password" : "text"}
                        placeholder={field.placeholder || `请输入 ${field.label}`}
                        value={values[field.name] || field.default_value || ""}
                        onChange={(e) => handleChange(field.name, e.target.value)}
                        disabled={isSubmitting}
                        className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                      />
                    )}
                  </div>
                ))}
              </div>

              <button
                onClick={handleSubmit}
                disabled={isSubmitting || !requiredFilled}
                className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isSubmitting ? "保存中..." : "保存配置"}
              </button>
            </>
          ) : (
            <div className="text-sm text-slate-600 dark:text-slate-400 bg-white/50 dark:bg-slate-800/50 rounded-lg p-2">
              <span className="font-medium">已配置:</span> {event.providedVariables?.join(", ")}
            </div>
          )}
        </div>
      </div>
      <div className="pl-11">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * TimelineEventItem component
 */
export const TimelineEventItem: React.FC<TimelineEventItemProps> = memo(
  ({ event, isStreaming = false, allEvents }) => {
    const events = allEvents ?? [event];

    switch (event.type) {
      case "user_message":
        return (
          <div className="my-4 animate-slide-up">
            <div className="flex items-start justify-end gap-3">
              <div className="flex flex-col items-end gap-1 max-w-[80%]">
                <UserMessage content={event.content} />
                <TimeBadge timestamp={event.timestamp} />
              </div>
            </div>
          </div>
        );

      case "assistant_message":
        return (
          <div className="my-4 animate-slide-up">
            <div className="flex items-start gap-3">
              <div className="flex flex-col gap-1 flex-1">
                <AssistantMessage
                  content={event.content}
                  isStreaming={isStreaming}
                  generatedAt={new Date(event.timestamp).toISOString()}
                />
                <div className="pl-11">
                  <TimeBadge timestamp={event.timestamp} />
                </div>
              </div>
            </div>
          </div>
        );

      case "thought":
        return (
          <div className="my-3 animate-slide-up">
            <ThoughtItem event={event} isStreaming={isStreaming} />
          </div>
        );

      case "act":
        return (
          <div className="my-3 animate-slide-up">
            <ActItem event={event} allEvents={events} />
          </div>
        );

      case "observe":
        return (
          <div className="my-3 animate-slide-up">
            <ObserveItem event={event} allEvents={events} />
          </div>
        );

      case "work_plan":
        return (
          <div className="my-3 animate-slide-up">
            <WorkPlanItem event={event} />
          </div>
        );

      case "step_start":
        if (!event.stepDescription || event.stepDescription.trim() === "") {
          return null;
        }
        return (
          <div className="animate-slide-up">
            <StepStartItem event={event} />
          </div>
        );

      case "step_end":
        return null;

      case "text_delta":
        return (
          <div className="my-4 animate-slide-up">
            <TextDeltaItem event={event} />
          </div>
        );

      case "text_start":
        return null;

      case "text_end":
        return (
          <div className="my-4 animate-slide-up">
            <TextEndItem event={event} />
          </div>
        );

      // Human-in-the-loop events
      case "clarification_asked":
        return (
          <div className="my-3 animate-slide-up">
            <ClarificationAskedItem event={event} />
          </div>
        );

      case "clarification_answered":
        // Already shown as part of clarification_asked when answered
        return null;

      case "decision_asked":
        return (
          <div className="my-3 animate-slide-up">
            <DecisionAskedItem event={event} />
          </div>
        );

      case "decision_answered":
        // Already shown as part of decision_asked when answered
        return null;

      case "env_var_requested":
        return (
          <div className="my-3 animate-slide-up">
            <EnvVarRequestedItem event={event} />
          </div>
        );

      case "env_var_provided":
        // Already shown as part of env_var_requested when answered
        return null;

      default:
        console.warn(
          "Unknown event type in TimelineEventItem:",
          (event as { type: string }).type
        );
        return null;
    }
  }
);

TimelineEventItem.displayName = "TimelineEventItem";

export default TimelineEventItem;
